import discord
from discord.ext import commands, tasks
import logging
import os
import traceback # 상세한 오류 로깅을 위해 추가
from typing import Dict, List, Tuple, Optional, Literal

import config # 설정 임포트

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
    'bot.cogs.schedule_cog', # <<< 새로운 ScheduleCog 추가
]

AVAILABLE_MOODS = Literal["기본", "장난", "진지"]

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
        logger.info("Initialized state management attributes.")

        # --- Task Management ---
        self.scheduler_initialized = False
        self.initiate_checker_loop_task: Optional[tasks.Loop] = None

    # --- State Management Methods ---
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
