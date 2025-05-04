import discord
from discord.ext import commands
import logging
import os
import traceback # 상세한 오류 로깅을 위해 추가

import config # 설정 임포트
# 아래 tasks 임포트는 tasks/ 디렉토리 생성 후 활성화
# from tasks.scheduler import setup_scheduler
# from tasks.initiate_checker import start_initiate_checker

logger = logging.getLogger(__name__)

# Cogs 로드 목록 (나중에 cogs/ 디렉토리에 파일 생성 후 경로 지정)
# 예시: INITIAL_EXTENSIONS = ['bot.cogs.general', 'bot.cogs.notion_features', ...]
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
        intents.messages = True         # 메시지 수신 관련
        intents.message_content = True  # 메시지 내용 접근 (중요!)
        intents.guilds = True           # 서버 정보 접근
        intents.members = True          # 멤버 정보 접근 (일부 기능에 필요할 수 있음)
        intents.dm_messages = True      # DM 메시지 수신

        # 부모 클래스 초기화
        super().__init__(command_prefix=config.BOT_PREFIX, intents=intents)

        # 여기에 봇의 상태나 필요한 서비스(세션 등)를 저장할 수 있습니다.
        # 예: self.http_session = aiohttp.ClientSession()
        # 예: self.conversation_logs = {} # 사용자별 대화 기록 관리 등

        self.scheduler_initialized = False # 스케줄러 중복 초기화 방지 플래그
        self.initiate_checker_task = None # 선톡 태스크 객체 저장용

    async def setup_hook(self):
        """
        봇이 Discord에 로그인한 후, Websocket에 연결하기 전에 호출되는 비동기 설정 함수.
        Cogs 로드, 백그라운드 태스크 시작 등에 사용됩니다.
        """
        logger.info(f"Setting up bot - Logged in as {self.user} (ID: {self.user.id})")

        # Cog 로드
        logger.info("Loading cogs...")
        for extension in INITIAL_EXTENSIONS:
            try:
                await self.load_extension(extension)
                logger.info(f"Successfully loaded cog: {extension}")
            except commands.ExtensionNotFound:
                logger.error(f"Cog not found: {extension}")
            except commands.ExtensionAlreadyLoaded:
                logger.warning(f"Cog already loaded: {extension}")
            except commands.NoEntryPointError:
                logger.error(f"Cog '{extension}' does not have a setup function.")
            except commands.ExtensionFailed as e:
                logger.error(f"Failed to load cog {extension}: {e.__class__.__name__} - {e}", exc_info=True)
                # traceback.print_exc() # 상세 오류 출력 필요시

        logger.info("Cogs loading process finished.")

        # --- 백그라운드 태스크 시작 ---
        # 스케줄러 설정 및 시작 (scheduler.py 리팩토링 후 활성화)
        # if not self.scheduler_initialized:
        #     try:
        #         setup_scheduler(self) # 봇 인스턴스 전달
        #         self.scheduler_initialized = True
        #         logger.info("Scheduler initialized successfully.")
        #     except Exception as e:
        #         logger.exception("Failed to initialize scheduler:")
        # else:
        #      logger.info("Scheduler already initialized.")

        # 선톡 검사 태스크 시작 (initiate_checker.py 리팩토링 후 활성화)
        # try:
        #     self.initiate_checker_task = start_initiate_checker(self) # 봇 인스턴스 전달
        #     logger.info("Initiate checker task started.")
        # except Exception as e:
        #     logger.exception("Failed to start initiate checker task:")

        # 여기에 추가적인 비동기 초기화 작업 수행 가능
        # 예: 데이터베이스 연결, HTTP 세션 생성 등

    async def on_ready(self):
        """봇이 준비되고 모든 길드 정보를 받았을 때 호출됩니다."""
        # setup_hook에서 대부분의 초기화를 수행하므로 여기서는 간단한 로그만 남깁니다.
        logger.info(f"Bot is ready and online! Synced {len(self.guilds)} guild(s).")
        # 필요하다면 여기서 슬래시 커맨드 동기화 등 수행
        # try:
        #     synced = await self.tree.sync()
        #     logger.info(f"Synced {len(synced)} application commands.")
        # except Exception as e:
        #     logger.error(f"Failed to sync application commands: {e}")

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """명령어 처리 중 오류 발생 시 호출됩니다."""
        if isinstance(error, commands.CommandNotFound):
            # 정의되지 않은 명령어는 무시하거나 사용자에게 알림
            # await ctx.send("크크… 그런 명령어는 없어.")
            logger.debug(f"Command not found: {ctx.message.content}")
            return
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"크크… 명령어를 사용하려면 `{error.param.name}` 정보가 필요해.")
        elif isinstance(error, commands.UserInputError):
            await ctx.send("크크… 명령어를 잘못 사용한 것 같아. 다시 확인해줄래?")
        elif isinstance(error, commands.CheckFailure):
            await ctx.send("크크… 이 명령어는 사용할 수 없어.")
        elif isinstance(error, commands.CommandInvokeError):
            original = error.original
            logger.error(f'Command {ctx.command} failed: {original.__class__.__name__} - {original}', exc_info=original)
            await ctx.send("크크… 명령을 처리하는 중에 문제가 생겼어. 잠시 후에 다시 시도해줘.")
        else:
            # 기타 예상치 못한 오류
            logger.error(f"Unhandled command error: {error}", exc_info=error)
            await ctx.send("크크… 알 수 없는 오류가 발생했어.")

    async def start_bot(self):
        """설정 파일에서 토큰을 가져와 봇을 시작합니다."""
        logger.info("Attempting to start the bot...")
        if not config.DISCORD_BOT_TOKEN:
            logger.critical("Bot token is missing. Cannot start.")
            return
        try:
            await self.start(config.DISCORD_BOT_TOKEN)
        except discord.LoginFailure:
            logger.critical("Failed to log in with the provided bot token. Check the token.")
        except Exception as e:
            logger.critical(f"An error occurred while starting the bot: {e}", exc_info=True)
        finally:
            # 봇 종료 시 리소스 정리 (예: HTTP 세션 닫기)
            # if hasattr(self, 'http_session') and not self.http_session.closed:
            #     await self.http_session.close()
            #     logger.info("Closed aiohttp session.")
            logger.info("Bot has stopped.")
