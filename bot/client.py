import discord
from discord.ext import commands, tasks
import logging
import os
import traceback 
from typing import Dict, List, Tuple, Optional, Literal, get_args
import asyncio
import random
import config 
from datetime import datetime

# --- Service Imports ---
from services.ai_service import AIService
from services.notion_service import NotionService
from services.midjourney_service import MidjourneyService

# --- Task Imports ---
from tasks.scheduler import setup_scheduler, shutdown_scheduler
from tasks.initiate_checker import start_initiate_checker, stop_initiate_checker

logger = logging.getLogger(__name__)

# 로드할 Cogs 목록에 ScheduleCog 추가
INITIAL_EXTENSIONS = [
    'bot.cogs.general',
    'bot.cogs.notion_features',
    'bot.cogs.midjourney',
    'bot.cogs.reminders',
    'bot.cogs.schedule_cog', 
    'bot.cogs.mood_cog'
]

AVAILABLE_MOODS = Literal["기본", "장난", "진지"]

AVAILABLE_KIYO_EMOTIONS = Literal[
    "고요함",    # 평온하고 관찰자적인 기본 상태
    "흥미",      # 무언가에 호기심을 느끼거나 지적 자극을 받은 상태
    "냉소",      # 상황이나 대상에 대해 약간의 비판이나 회의감을 느끼는 상태
    "불쾌함",    # 무례함이나 부조리함에 내적으로 불쾌감을 느끼지만 겉으로는 잘 드러내지 않음
    "탐구심",    # 특정 주제나 현상에 대해 깊이 파고들고 싶어 하는 학자적 욕구
    "미묘한 슬픔" # 말로 표현하기 어려운, 잔잔하게 깔린 슬픔이나 공허함 (드물게 나타남)
]

class KiyoBot(commands.Bot):
    """신구지 코레키요 봇 클라이언트 클래스"""

    def __init__(self):
        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        intents.dm_messages = True

        super().__init__(command_prefix=config.BOT_PREFIX, intents=intents,
                         case_insensitive=True)

        # --- Service Initialization ---
        logger.info("Initializing services...")
        try:
            self.ai_service = AIService()
            self.notion_service = NotionService()
            self.midjourney_service = MidjourneyService()
            logger.info("Services initialized successfully.")
        except ValueError as e:
            logger.critical(f"Failed to initialize services: {e}")
            raise RuntimeError(f"Service initialization failed: {e}") from e
        except Exception as e:
            logger.critical(f"Unexpected error during service initialization: {e}", exc_info=True)
            raise RuntimeError("Unexpected error during service initialization.") from e

        # --- State Management Initialization ---
        self.conversation_logs: Dict[int, List[Tuple[str, str, int]]] = {}
        # self.last_diary_page_ids: Dict[int, str] = {} # <<< 기존 채널별 ID 관리에서 변경
        self.current_diary_page_id_for_mj: Optional[str] = None # MJ 이미지가 연결될 단일 ID
        self.log_max_length = 50
        self.current_conversation_mood: AVAILABLE_MOODS = "기본"
        self.current_kiyo_emotion: AVAILABLE_KIYO_EMOTIONS = "고요함" # 기본 감정 상태
        self.last_interaction_time: datetime = datetime.now(config.KST) # 마지막 상호작용 시간 (감정 변화 타이머용)
        self.emotion_decay_task: Optional[asyncio.Task] = None # 감정 변화 관리 태스크
        logger.info("Initialized state management attributes.")

        # --- Task Management ---
        self.scheduler_initialized = False
        self.initiate_checker_loop_task: Optional[tasks.Loop] = None

    # --- State Management Methods ---
    def set_kiyo_emotion(self, emotion: AVAILABLE_KIYO_EMOTIONS):
        """키요의 현재 감정 상태를 설정합니다."""
        if emotion != self.current_kiyo_emotion: # 감정이 실제로 변경될 때만 로그 기록
            self.current_kiyo_emotion = emotion
            logger.info(f"Kiyo's internal emotion set to: {emotion}")
        else:
            logger.debug(f"Kiyo's emotion is already {emotion}.")
            pass

    def get_kiyo_emotion(self) -> AVAILABLE_KIYO_EMOTIONS:
        """키요의 현재 감정 상태를 반환합니다."""
        return self.current_kiyo_emotion

    def update_last_interaction_time(self):
        """마지막 사용자 상호작용 시간을 현재 시간으로 갱신합니다."""
        self.last_interaction_time = datetime.now(config.KST)
        logger.debug(f"Last interaction time updated to: {self.last_interaction_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
    def get_conversation_log(self, channel_id: int) -> List[Tuple[str, str, int]]:
        return self.conversation_logs.setdefault(channel_id, [])

    def add_conversation_log(self, channel_id: int, speaker: str, text: str):
        log = self.get_conversation_log(channel_id)
        log.append((speaker, text, channel_id))
        if len(log) > self.log_max_length:
            self.conversation_logs[channel_id] = log[-self.log_max_length:]

    def clear_conversation_log(self, channel_id: int):
        if channel_id in self.conversation_logs:
            self.conversation_logs[channel_id] = []
            logger.info(f"Cleared conversation log for channel {channel_id}.")

    # --- Midjourney 이미지 연결을 위한 ID 관리 메소드 (수정/변경) ---
    def set_current_diary_page_id_for_mj(self, page_id: Optional[str]):
        """Midjourney 이미지가 연결될 현재 작업 중인 일기 페이지 ID 저장"""
        self.current_diary_page_id_for_mj = page_id
        if page_id:
            logger.info(f"Set current diary page ID for Midjourney to: {page_id}")
        else:
            logger.info("Cleared current diary page ID for Midjourney.")

    def get_current_diary_page_id_for_mj(self) -> Optional[str]:
        """Midjourney 이미지가 연결될 현재 작업 중인 일기 페이지 ID 조회"""
        return self.current_diary_page_id_for_mj

    def set_conversation_mood(self, mood: AVAILABLE_MOODS):
        """봇의 현재 대화 무드를 설정합니다."""
        # 사용 가능한 무드인지 확인 (선택적이지만 권장)
        # typing.get_args(AVAILABLE_MOODS) 를 사용하여 Literal의 값들을 가져올 수 있음
        # if mood not in get_args(AVAILABLE_MOODS):
        #     logger.warning(f"Attempted to set invalid mood: {mood}")
        #     return False # 또는 예외 발생
        self.current_conversation_mood = mood
        logger.info(f"Conversation mood set to: {mood}")
        # return True

    def get_conversation_mood(self) -> AVAILABLE_MOODS:
        """봇의 현재 대화 무드를 반환합니다."""
        return self.current_conversation_mood

    # --- Emotion Decay Manager (백그라운드 태스크) ---
    async def emotion_decay_manager(self):
        """일정 시간 대화가 없으면 키요의 감정을 랜덤하게 변경하는 관리자 태스크."""
        await self.wait_until_ready() # 봇이 준비될 때까지 대기
        logger.info("Kiyo's emotion decay manager started. Checking interval: %s seconds, Inactivity threshold: %s seconds.",
                    config.KIYO_EMOTION_DECAY_CHECK_INTERVAL_SECONDS,
                    config.KIYO_EMOTION_CHANGE_INACTIVITY_THRESHOLD_SECONDS)
        while not self.is_closed():
            try:
                # config.py에 정의된 체크 주기로 변경
                await asyncio.sleep(config.KIYO_EMOTION_DECAY_CHECK_INTERVAL_SECONDS)

                now = datetime.now(config.KST)
                time_since_last_interaction = now - self.last_interaction_time
                
                # config.py에 정의된 비활성 임계값으로 변경
                if time_since_last_interaction.total_seconds() >= config.KIYO_EMOTION_CHANGE_INACTIVITY_THRESHOLD_SECONDS:
                    current_emotion = self.get_kiyo_emotion()
                    available_emotions_list = list(get_args(AVAILABLE_KIYO_EMOTIONS))
                    
                    new_emotion_pool = [e for e in available_emotions_list if e != current_emotion]
                    
                    if new_emotion_pool:
                        new_random_emotion = random.choice(new_emotion_pool)
                        self.set_kiyo_emotion(new_random_emotion) # 새로운 감정으로 설정
                        # logger.info(f"Kiyo's emotion auto-changed to '{new_random_emotion}' due to inactivity threshold reached.") # 로그 메시지 약간 수정
                        
                        # 감정 변경 후에는 타이머 리셋을 위해 상호작용 시간 갱신
                        self.update_last_interaction_time() 
                        
                        # (선택적) 감정 변경에 대한 내적 독백 생성 및 DM 전송
                        if config.SEND_EMOTION_CHANGE_MONOLOGUE: # config 값 확인
                            # target_user_dm을 가져오는 헬퍼 함수가 필요하거나, 직접 구현
                            target_user = await self.fetch_user(config.TARGET_USER_ID) if config.TARGET_USER_ID else None
                            if target_user:
                                dm_channel = target_user.dm_channel or await target_user.create_dm()
                                if dm_channel:
                                    # ai_service에 monologue 생성 함수가 정의되어 있다고 가정
                                    if hasattr(self.ai_service, 'generate_internal_monologue_for_emotion_change'):
                                        monologue = await self.ai_service.generate_internal_monologue_for_emotion_change(new_random_emotion, current_emotion)
                                        if monologue:
                                            try:
                                                await dm_channel.send(f"*{monologue}*")
                                                logger.info(f"Sent emotion change monologue to user for new emotion: {new_random_emotion}")
                                            except discord.HTTPException as e:
                                                logger.error(f"Failed to send emotion change monologue: {e}")
                                    else:
                                        logger.warning("AIService does not have 'generate_internal_monologue_for_emotion_change' method.")
                    # else:
                        # logger.debug("No other emotions available to randomly switch to.")
                # else:
                #      logger.debug(f"Time since last interaction: {time_since_last_interaction.total_seconds() / 60:.1f} minutes. No emotion change needed.")

            except asyncio.CancelledError:
                logger.info("Emotion decay manager task cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in emotion_decay_manager: {e}", exc_info=True)
                await asyncio.sleep(60 * 5) # 오류 발생 시 5분 후 재시도


    # --- Bot Lifecycle Methods ---
    async def setup_hook(self):
        logger.info(f"Running setup hook... Logged in as {self.user} (ID: {self.user.id if self.user else 'N/A'})") # self.user가 None일 수 있음

        # Cog 로드
        logger.info("Loading cogs...")
        for extension in INITIAL_EXTENSIONS: # 수정된 INITIAL_EXTENSIONS 사용
            try:
                await self.load_extension(extension)
                logger.info(f"Successfully loaded cog: {extension}")
            except Exception as e:
                logger.error(f"Failed to load cog {extension}: {e.__class__.__name__} - {e}", exc_info=True)
        logger.info("Cogs loading finished.")

        # 백그라운드 태스크 시작
        if not self.scheduler_initialized:
            try:
                setup_scheduler(self)
                self.scheduler_initialized = True
            except Exception as e:
                logger.exception("Failed to initialize scheduler:")
        else:
             logger.info("Scheduler already initialized.")

        # <<< 감정 변화 관리 태스크 시작 >>>
        if not (self.emotion_decay_task and not self.emotion_decay_task.done()):
            self.emotion_decay_task = self.loop.create_task(self.emotion_decay_manager())

        try:
            loop_task = start_initiate_checker(self)
            if loop_task:
                 self.initiate_checker_loop_task = loop_task
                
        except Exception as e:
            logger.exception("Failed to start initiate checker task:")

        logger.info("Bot setup hook complete.")

    async def on_ready(self):
        logger.info("="*30)
        logger.info(f" Kiyo Bot is Ready! ")
        logger.info(f" User: {self.user}") # self.user는 on_ready 시점에는 항상 존재
        logger.info(f" ID: {self.user.id}")
        logger.info(f" Guilds: {len(self.guilds)}")
        logger.info("="*30)
        # await self.change_presence(activity=discord.Game(name="민속 조사"))

    async def close(self):
        logger.info("Closing Kiyo Bot...")
        logger.info("Stopping background tasks...")
        if self.initiate_checker_loop_task and self.initiate_checker_loop_task.is_running():
            stop_initiate_checker()
        shutdown_scheduler()

         # <<< 감정 변화 관리 태스크 캔슬 >>>
        if self.emotion_decay_task and not self.emotion_decay_task.done():
            self.emotion_decay_task.cancel()
            try: await self.emotion_decay_task # 캔슬 완료 대기
            except asyncio.CancelledError: logger.info("Emotion decay manager task successfully cancelled.")
            except Exception as e: logger.error(f"Error during emotion_decay_task cancellation: {e}", exc_info=True)

        logger.info("Closing service sessions...")
        if hasattr(self.notion_service, 'close_session'):
            await self.notion_service.close_session()
        # if hasattr(self.ai_service, 'close_session'): await self.ai_service.close_session() # ai_service에 close_session이 있다면

        logger.info("Closing discord.py client...")
        await super().close()
        logger.info("Kiyo Bot closed gracefully.")

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        # ... (기존 on_command_error 로직 동일) ...
        ignored = (commands.CommandNotFound, )
        if isinstance(error, commands.CommandNotFound):
             logger.debug(f"Command not found: {ctx.message.content}")
             return
        if isinstance(error, commands.UserInputError): await ctx.send(f"크크… 명령어를 잘못 사용한 것 같아. `!help {ctx.command.qualified_name}` 참고해줘.", delete_after=10)
        elif isinstance(error, commands.CheckFailure): logger.warning(f"Command check failed for {ctx.command} by {ctx.author}: {error}"); await ctx.send("크크… 이 명령어는 사용할 수 없어.", delete_after=10)
        elif isinstance(error, commands.CommandInvokeError): original = error.original; logger.error(f'Command {ctx.command.qualified_name} failed: {original.__class__.__name__} - {original}', exc_info=original); await ctx.send("크크… 명령을 처리하는 중에 문제가 생겼어. 잠시 후에 다시 시도해줘.")
        else: logger.error(f"Unhandled error in command {ctx.command}: {error}", exc_info=error); await ctx.send("크크… 알 수 없는 오류가 발생했어.")


    async def start_bot(self):
        logger.info("Attempting to start the bot...")
        if not config.DISCORD_BOT_TOKEN:
            logger.critical("Bot token is missing. Cannot start.")
            return
        try:
            await self.start(config.DISCORD_BOT_TOKEN)
        except discord.LoginFailure:
            logger.critical("Failed to log in with the provided bot token. Check the token.")
        except Exception as e:
             logger.critical(f"An unexpected error occurred while starting or running the bot: {e}", exc_info=True)
        finally:
            if not self.is_closed():
                await self.close()
