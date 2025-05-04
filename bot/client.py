import discord
from discord.ext import commands, tasks
import logging
import os
import traceback # 상세한 오류 로깅을 위해 추가
from typing import Dict, List, Tuple, Optional

import config # 설정 임포트

# --- Service Imports ---
# 실제 서비스 클래스 임포트
from services.ai_service import AIService
from services.notion_service import NotionService
from services.midjourney_service import MidjourneyService

# --- Task Imports ---
# 실제 태스크 시작/종료 함수 임포트
from tasks.scheduler import setup_scheduler, shutdown_scheduler
from tasks.initiate_checker import start_initiate_checker, stop_initiate_checker

logger = logging.getLogger(__name__)

# 로드할 Cogs 목록
INITIAL_EXTENSIONS = [
    'bot.cogs.general',
    'bot.cogs.notion_features',
    'bot.cogs.midjourney',
    'bot.cogs.reminders',
]

class KiyoBot(commands.Bot):
    """신구지 코레키요 봇 클라이언트 클래스"""

    def __init__(self):
        # 필요한 Intents 설정
        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True
        intents.guilds = True
        intents.members = True # 서버 멤버 정보 접근 (사용자 객체 가져오기 등에 필요할 수 있음)
        intents.dm_messages = True

        # 부모 클래스 초기화
        super().__init__(command_prefix=config.BOT_PREFIX, intents=intents)

        # --- Service Initialization ---
        # 각 서비스 클래스의 인스턴스를 생성하여 봇 객체에 저장
        # 다른 모듈(Cogs, Tasks)에서는 self.bot.ai_service 등으로 접근 가능
        logger.info("Initializing services...")
        self.ai_service = AIService()
        self.notion_service = NotionService() # Notion API 키는 NotionService 내부에서 확인
        self.midjourney_service = MidjourneyService()
        logger.info("Services initialized.")

        # --- State Management Initialization ---
        # 채널 ID를 키로 사용하는 딕셔너리
        self.conversation_logs: Dict[int, List[Tuple[str, str, int]]] = {}
        # 채널 ID를 키로 사용하는 딕셔너리
        self.last_diary_page_ids: Dict[int, str] = {}
        logger.info("Initialized state management attributes (conversation_logs, last_diary_page_ids).")

        # --- Task Management ---
        self.scheduler_initialized = False
        self.initiate_checker_loop_task: Optional[tasks.Loop] = None # Task 객체 저장

    # --- State Management Methods ---
    def get_conversation_log(self, channel_id: int) -> List[Tuple[str, str, int]]:
        """채널 ID에 해당하는 대화 기록 반환 (없으면 빈 리스트 생성)"""
        if channel_id not in self.conversation_logs:
            self.conversation_logs[channel_id] = []
        return self.conversation_logs[channel_id]

    def add_conversation_log(self, channel_id: int, speaker: str, text: str):
        """채널 대화 기록에 새 메시지 추가"""
        log = self.get_conversation_log(channel_id) # 없으면 생성됨
        # speaker, text, channel_id 튜플 저장
        log.append((speaker, text, channel_id))
        # 로그 길이 제한 (예: 최근 50개만 유지)
        max_log_length = 50
        if len(log) > max_log_length:
            # 오래된 로그부터 제거
            self.conversation_logs[channel_id] = log[-max_log_length:]
            logger.debug(f"Trimmed conversation log for channel {channel_id} to {max_log_length} entries.")

    def clear_conversation_log(self, channel_id: int):
        """채널 대화 기록 초기화"""
        if channel_id in self.conversation_logs:
            self.conversation_logs[channel_id] = []
            logger.info(f"Cleared conversation log for channel {channel_id}.")

    def set_last_diary_page_id(self, channel_id: int, page_id: str):
        """채널별 마지막 일기 페이지 ID 저장"""
        self.last_diary_page_ids[channel_id] = page_id
        logger.info(f"Set last diary page ID for channel {channel_id} to {page_id}")

    def get_last_diary_page_id(self, channel_id: int) -> Optional[str]:
        """채널별 마지막 일기 페이지 ID 조회"""
        return self.last_diary_page_ids.get(channel_id)

    def get_overall_latest_diary_page_id(self) -> Optional[str]:
         """전체 채널 중 가장 최근에 저장된 일기 페이지 ID 반환 (Midjourney용 임시 방편)"""
         if not self.last_diary_page_ids:
             return None
         # 저장된 값들 중 마지막 값 반환 (가장 최근 가정)
         # 더 정확하게 하려면 timestamp와 함께 저장 필요
         return list(self.last_diary_page_ids.values())[-1]


    # --- Bot Lifecycle Methods ---
    async def setup_hook(self):
        """
        봇 비동기 설정: Cogs 로드, 백그라운드 태스크 시작, 서비스 초기화 등
        """
        logger.info(f"Setting up bot - Logged in as {self.user} (ID: {self.user.id})")

        # Cog 로드
        logger.info("Loading cogs...")
        loaded_cogs = []
        failed_cogs = []
        for extension in INITIAL_EXTENSIONS:
            try:
                await self.load_extension(extension)
                logger.info(f"Successfully loaded cog: {extension}")
                loaded_cogs.append(extension)
            except Exception as e:
                logger.error(f"Failed to load cog {extension}: {e.__class__.__name__} - {e}", exc_info=True)
                failed_cogs.append(extension)
        logger.info(f"Cogs loading finished. Loaded: {len(loaded_cogs)}, Failed: {len(failed_cogs)}")
        if failed_cogs:
             logger.error(f"Failed to load the following cogs: {', '.join(failed_cogs)}")

        # --- 백그라운드 태스크 시작 ---
        # 스케줄러 설정 및 시작
        if not self.scheduler_initialized:
            try:
                # setup_scheduler 함수는 bot 인스턴스를 받아 스케줄러를 설정하고 시작함
                setup_scheduler(self)
                self.scheduler_initialized = True
                # logger.info("Scheduler initialized successfully.") # setup_scheduler 내부 로그 사용
            except Exception as e:
                logger.exception("Failed to initialize scheduler:")
        else:
             logger.info("Scheduler already initialized.")

        # 선톡 검사 태스크 시작
        try:
            # start_initiate_checker 함수는 bot 인스턴스를 받아 루프를 시작하고 task 객체 반환
            self.initiate_checker_loop_task = start_initiate_checker(self)
            # logger.info("Initiate checker task started.") # start_initiate_checker 내부 로그 사용
        except Exception as e:
            logger.exception("Failed to start initiate checker task:")

        logger.info("Bot setup complete.")

    async def on_ready(self):
        """봇 준비 완료 이벤트"""
        logger.info(f"Bot is ready and online! Synced {len(self.guilds)} guild(s).")
        # 필요 시 슬래시 커맨드 동기화 등 추가 작업 수행

    async def close(self):
        """봇 종료 시 리소스 정리"""
        logger.info("Closing Kiyo Bot...")

        # 1. 백그라운드 태스크 종료
        logger.info("Stopping background tasks...")
        if self.initiate_checker_loop_task:
            stop_initiate_checker() # tasks/initiate_checker.py의 함수 호출
        shutdown_scheduler() # tasks/scheduler.py의 함수 호출

        # 2. 서비스 리소스 정리 (예: aiohttp 세션 닫기)
        logger.info("Closing service sessions...")
        if hasattr(self, 'notion_service') and self.notion_service:
            await self.notion_service.close_session()
        # 다른 서비스들도 close 메소드가 있다면 호출
        # await self.ai_service.close()
        # await self.midjourney_service.close()

        # 3. discord.py Bot 종료 처리
        logger.info("Closing discord.py client...")
        await super().close()
        logger.info("Kiyo Bot closed gracefully.")

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """명령어 오류 처리 핸들러"""
        # 오류 처리 로직 (기존과 유사하게 유지 또는 개선)
        ignored = (commands.CommandNotFound, commands.UserInputError, commands.CheckFailure)

        if isinstance(error, ignored):
            if isinstance(error, commands.CommandNotFound):
                 logger.debug(f"Command not found: {ctx.message.content}")
                 # await ctx.send("크크… 그런 명령어는 없어.", delete_after=5) # 필요시 사용자 알림
                 return
            elif isinstance(error, commands.UserInputError):
                 await ctx.send(f"크크… 명령어를 잘못 사용한 것 같아. `!help {ctx.command.qualified_name}` 참고해줘.", delete_after=10)
                 return
            elif isinstance(error, commands.CheckFailure):
                 logger.warning(f"Command check failed for {ctx.command}: {error}")
                 await ctx.send("크크… 이 명령어는 사용할 수 없어.", delete_after=10)
                 return

        # 특정 명령어에서 발생한 예외 처리 (CommandInvokeError)
        elif isinstance(error, commands.CommandInvokeError):
            original_error = error.original
            logger.error(f'Command {ctx.command} failed with error: {original_error.__class__.__name__} - {original_error}', exc_info=original_error)
            await ctx.send("크크… 명령을 처리하는 중에 문제가 생겼어. 잠시 후에 다시 시도해줘.")

        # 그 외 처리되지 않은 오류
        else:
            logger.error(f"Unhandled command error for {ctx.command}: {error}", exc_info=error)
            await ctx.send("크크… 알 수 없는 오류가 발생했어.")


    async def start_bot(self):
        """설정 파일에서 토큰을 가져와 봇을 시작하고 종료 시 close 호출"""
        logger.info("Attempting to start the bot...")
        if not config.DISCORD_BOT_TOKEN:
            logger.critical("Bot token is missing. Cannot start.")
            return

        try:
            # 봇 시작 (로그인 및 Websocket 연결)
            await self.start(config.DISCORD_BOT_TOKEN)
        except discord.LoginFailure:
            logger.critical("Failed to log in with the provided bot token. Check the token.")
        except Exception as e:
            logger.critical(f"An error occurred while starting or running the bot: {e}", exc_info=True)
        finally:
            # 봇이 어떤 이유로든 종료되면 close 메소드 호출
            if not self.is_closed():
                await self.close()
