import discord
from discord.ext import commands, tasks
import logging
import os
import traceback # 상세한 오류 로깅을 위해 추가
from typing import Dict, List, Tuple, Optional

import config # 설정 임포트

# --- Service Imports ---
from services.ai_service import AIService
from services.notion_service import NotionService
from services.midjourney_service import MidjourneyService

# --- Task Imports ---
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
        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        intents.dm_messages = True

        super().__init__(command_prefix=config.BOT_PREFIX, intents=intents,
                         # Case-insensitive commands (선택 사항)
                         case_insensitive=True)

        # --- Service Initialization ---
        logger.info("Initializing services...")
        try:
            self.ai_service = AIService()
            self.notion_service = NotionService()
            self.midjourney_service = MidjourneyService()
            logger.info("Services initialized successfully.")
        except ValueError as e: # 예: Notion API 키 누락 시
            logger.critical(f"Failed to initialize services: {e}")
            # 서비스 초기화 실패 시 봇 실행 불가
            raise RuntimeError(f"Service initialization failed: {e}") from e
        except Exception as e:
            logger.critical(f"Unexpected error during service initialization: {e}", exc_info=True)
            raise RuntimeError("Unexpected error during service initialization.") from e


        # --- State Management Initialization ---
        self.conversation_logs: Dict[int, List[Tuple[str, str, int]]] = {}
        self.last_diary_page_ids: Dict[int, str] = {}
        self.log_max_length = 50 # 대화 로그 최대 길이 설정
        logger.info("Initialized state management attributes.")

        # --- Task Management ---
        self.scheduler_initialized = False
        self.initiate_checker_loop_task: Optional[tasks.Loop] = None

    # --- State Management Methods ---
    def get_conversation_log(self, channel_id: int) -> List[Tuple[str, str, int]]:
        """채널 ID에 해당하는 대화 기록 반환 (없으면 빈 리스트 생성)"""
        return self.conversation_logs.setdefault(channel_id, [])

    def add_conversation_log(self, channel_id: int, speaker: str, text: str):
        """채널 대화 기록에 새 메시지 추가 (최대 길이 유지)"""
        log = self.get_conversation_log(channel_id)
        # speaker, text, channel_id 튜플 저장 (channel_id는 중복 정보일 수 있으나 일단 유지)
        log.append((speaker, text, channel_id))
        # 로그 길이 제한
        if len(log) > self.log_max_length:
            self.conversation_logs[channel_id] = log[-self.log_max_length:]
            # logger.debug(f"Trimmed conversation log for channel {channel_id}")

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
         """전체 채널 중 가장 최근에 저장된 일기 페이지 ID 반환"""
         if not self.last_diary_page_ids:
             return None
         # 간단히 마지막 값 반환 (더 정확하려면 timestamp 필요)
         try:
             return list(self.last_diary_page_ids.values())[-1]
         except IndexError:
             return None


    # --- Bot Lifecycle Methods ---
    async def setup_hook(self):
        """봇 비동기 설정: Cogs 로드, 백그라운드 태스크 시작 등"""
        logger.info(f"Running setup hook... Logged in as {self.user} (ID: {self.user.id})")

        # Cog 로드
        logger.info("Loading cogs...")
        for extension in INITIAL_EXTENSIONS:
            try:
                await self.load_extension(extension)
                logger.info(f"Successfully loaded cog: {extension}")
            except Exception as e:
                logger.error(f"Failed to load cog {extension}: {e.__class__.__name__} - {e}", exc_info=True)
        logger.info("Cogs loading finished.")

        # --- 백그라운드 태스크 시작 ---
        # 스케줄러 시작
        if not self.scheduler_initialized:
            try:
                setup_scheduler(self) # tasks/scheduler.py의 함수 호출
                self.scheduler_initialized = True
            except Exception as e:
                logger.exception("Failed to initialize scheduler:")
        else:
             logger.info("Scheduler already initialized.")

        # 선톡 검사 태스크 시작
        try:
            # start_initiate_checker가 Loop 객체 또는 None 반환
            loop_task = start_initiate_checker(self) # tasks/initiate_checker.py의 함수 호출
            if loop_task:
                 self.initiate_checker_loop_task = loop_task
        except Exception as e:
            logger.exception("Failed to start initiate checker task:")

        logger.info("Bot setup hook complete.")

    async def on_ready(self):
        """봇 준비 완료 이벤트"""
        # setup_hook에서 대부분 처리하므로 간단히 로그만 남김
        logger.info("="*30)
        logger.info(f" Kiyo Bot is Ready! ")
        logger.info(f" User: {self.user}")
        logger.info(f" ID: {self.user.id}")
        logger.info(f" Guilds: {len(self.guilds)}")
        logger.info("="*30)
        # 활동 상태 설정 (선택적)
        # await self.change_presence(activity=discord.Game(name="민속 조사"))

    async def close(self):
        """봇 종료 시 리소스 정리"""
        logger.info("Closing Kiyo Bot...")
        # 1. 백그라운드 태스크 종료
        logger.info("Stopping background tasks...")
        if self.initiate_checker_loop_task and self.initiate_checker_loop_task.is_running():
            stop_initiate_checker()
        shutdown_scheduler()

        # 2. 서비스 리소스 정리
        logger.info("Closing service sessions...")
        if hasattr(self.notion_service, 'close_session'):
            await self.notion_service.close_session()
        # 다른 서비스 close 메소드 호출
        # if hasattr(self.ai_service, 'close'): await self.ai_service.close()

        # 3. discord.py Bot 종료 처리
        logger.info("Closing discord.py client...")
        await super().close() # 반드시 호출
        logger.info("Kiyo Bot closed gracefully.")

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """명령어 오류 처리 핸들러"""
        # 이전에 구현된 내용 유지 (필요시 수정)
        ignored = (commands.CommandNotFound, ) # UserInputError, CheckFailure는 사용자에게 알림

        if isinstance(error, commands.CommandNotFound):
             logger.debug(f"Command not found: {ctx.message.content}")
             return # 존재하지 않는 명령어는 조용히 무시

        if isinstance(error, commands.UserInputError):
            await ctx.send(f"크크… 명령어를 잘못 사용한 것 같아. `!help {ctx.command.qualified_name}` 참고해줘.", delete_after=10)
        elif isinstance(error, commands.CheckFailure):
             logger.warning(f"Command check failed for {ctx.command} by {ctx.author}: {error}")
             await ctx.send("크크… 이 명령어는 사용할 수 없어.", delete_after=10)
        elif isinstance(error, commands.CommandInvokeError):
            original = error.original
            logger.error(f'Command {ctx.command.qualified_name} failed: {original.__class__.__name__} - {original}', exc_info=original)
            # 사용자에게는 간단한 오류 메시지 표시
            await ctx.send("크크… 명령을 처리하는 중에 문제가 생겼어. 잠시 후에 다시 시도해줘.")
        else:
            logger.error(f"Unhandled error in command {ctx.command}: {error}", exc_info=error)
            await ctx.send("크크… 알 수 없는 오류가 발생했어.")


    async def start_bot(self):
        """설정 파일에서 토큰을 가져와 봇을 시작하고 종료 시 close 호출"""
        logger.info("Attempting to start the bot...")
        if not config.DISCORD_BOT_TOKEN:
            logger.critical("Bot token is missing. Cannot start.")
            # sys.exit(1) # main.py에서 처리
            return

        try:
            await self.start(config.DISCORD_BOT_TOKEN)
        except discord.LoginFailure:
            logger.critical("Failed to log in with the provided bot token. Check the token.")
            # 종료 로직은 finally에서 처리
        except Exception as e:
             logger.critical(f"An unexpected error occurred while starting or running the bot: {e}", exc_info=True)
             # 종료 로직은 finally에서 처리
        finally:
            # 봇이 어떤 이유로든 종료되면 close 메소드 호출 보장
            if not self.is_closed():
                await self.close()
