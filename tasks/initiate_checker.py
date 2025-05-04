import asyncio
import logging
from datetime import datetime, timedelta
import discord
from discord.ext import tasks, commands # commands.Bot 타입 힌트용

import config # 설정 임포트
from utils.activity_tracker import get_last_active # 마지막 활동 시간 유틸리티
# --- Service Imports ---
# from services.ai_service import AIService
# from services.notion_service import NotionService

# --- 임시 Placeholder Imports ---
from services.ai_service import PlaceholderAIService as AIService
from services.notion_service import PlaceholderNotionService as NotionService

logger = logging.getLogger(__name__)

@tasks.loop(minutes=config.INITIATE_CHECK_INTERVAL_MINUTES)
async def _check_initiate_message(bot: commands.Bot):
    """주기적으로 실행되어 선톡 조건을 확인하고 메시지를 보냅니다."""
    now = datetime.now(config.KST)
    current_hour = now.hour
    logger.debug(f"[Initiate Check] Running check at {now.strftime('%Y-%m-%d %H:%M:%S')}")

    # 0. 설정 값 확인
    if not config.TARGET_USER_ID:
        logger.warning("[Initiate Check] TARGET_USER_ID가 설정되지 않아 선톡 기능을 건너<0xEB><0x88>니다.")
        # 루프를 멈추거나, 주기적으로 경고만 남길 수 있음
        # _check_initiate_message.stop() # 필요시 루프 중지
        return

    # 1. 허용 시간대 확인 (시작 시간 <= 현재 시간 또는 현재 시간 <= 종료 시간)
    # 종료 시간이 시작 시간보다 작으면 (예: 23시 ~ 01시), 다음 날로 넘어가는 경우
    start_h = config.INITIATE_ALLOWED_START_HOUR
    end_h = config.INITIATE_ALLOWED_END_HOUR
    is_allowed_time = False
    if start_h <= end_h: # 같은 날 내 (예: 11시 ~ 18시)
        if start_h <= current_hour < end_h: # 종료 시간 '미만'으로 처리
             is_allowed_time = True
    else: # 다음 날로 넘어가는 경우 (예: 23시 ~ 01시)
        if current_hour >= start_h or current_hour < end_h: # 종료 시간 '미만'으로 처리
             is_allowed_time = True

    if not is_allowed_time:
        logger.debug(f"[Initiate Check] Not within allowed time window ({start_h:02d}:00 - {end_h:02d}:00 KST). Skipping.")
        return

    # 서비스 인스턴스 가져오기 (bot 객체에 할당되었다고 가정)
    ai_service: AIService = getattr(bot, 'ai_service', AIService())
    notion_service: NotionService = getattr(bot, 'notion_service', NotionService())

    try:
        # 2. 대상 유저 정보 가져오기
        user = await bot.fetch_user(config.TARGET_USER_ID)
        if not user:
            logger.warning(f"[Initiate Check] Target user ID {config.TARGET_USER_ID} not found.")
            return

        # 3. 마지막 활동 시간 확인
        last_active_time = get_last_active()
        if not last_active_time:
            logger.debug("[Initiate Check] No last active time recorded. Skipping.")
            return

        # 4. 비활성 시간 계산 및 확인
        time_gap = now - last_active_time
        gap_hours = time_gap.total_seconds() / 3600
        logger.debug(f"[Initiate Check] Last active: {last_active_time.strftime('%Y-%m-%d %H:%M:%S')}, Gap: {gap_hours:.2f} hours.")

        if gap_hours < config.INITIATE_MIN_GAP_HOURS:
            logger.debug(f"[Initiate Check] Time gap ({gap_hours:.2f} hrs) is less than minimum required ({config.INITIATE_MIN_GAP_HOURS} hrs). Skipping.")
            return

        # 5. 선톡 메시지 생성을 위한 컨텍스트 수집
        logger.debug("[Initiate Check] Fetching context for initiate message...")
        past_memories = await notion_service.fetch_recent_memories(limit=3) # 최근 기억 3개
        past_obs = await notion_service.fetch_recent_observations(limit=1)   # 최근 관찰 기록 1개 요약

        # 6. AI 서비스로 메시지 생성
        initiate_message = await ai_service.generate_initiate_message(
            gap_hours=gap_hours,
            past_memories=past_memories if isinstance(past_memories, list) else None, # 오류 방지
            past_obs=past_obs if isinstance(past_obs, str) else None # 오류 방지
        )

        if not initiate_message or initiate_message == "...": # 기본 메시지 또는 생성 실패 시
            logger.warning("[Initiate Check] Failed to generate initiate message or got default response.")
            return

        # 7. 사용자 DM 채널 가져와서 메시지 전송
        dm_channel = user.dm_channel or await user.create_dm()
        if not dm_channel:
             logger.error(f"[Initiate Check] Could not get or create DM channel for user {user.id}")
             return

        await dm_channel.send(initiate_message)
        logger.info(f"[Initiate Check] Sent initiate message to user {user.id} after {gap_hours:.2f} hours of inactivity.")

        # 선톡 후 마지막 활동 시간 업데이트 (선택적)
        # update_last_active() # 봇이 말을 걸었으므로 활동 시간 갱신? 정책에 따라 결정

    except discord.NotFound:
         logger.warning(f"[Initiate Check] Target user ID {config.TARGET_USER_ID} not found during check.")
    except discord.Forbidden:
         logger.error("[Initiate Check] Missing permissions to fetch user or send DM.")
         # 권한 문제 시 루프 중지 고려
         # _check_initiate_message.stop()
    except Exception as e:
        logger.error(f"[Initiate Check] Error during check: {e}", exc_info=True)


@_check_initiate_message.before_loop
async def before_initiate_check(bot: commands.Bot):
    """루프 시작 전 봇이 준비될 때까지 기다립니다."""
    await bot.wait_until_ready()
    logger.info("Initiate checker loop is starting after bot is ready.")

def start_initiate_checker(bot: commands.Bot) -> Optional[tasks.Loop]:
    """
    선톡 검사 루프를 시작합니다. bot/client.py의 setup_hook에서 호출됩니다.

    Args:
        bot: KiyoBot 인스턴스.

    Returns:
        시작된 tasks.Loop 객체 또는 실패 시 None.
    """
    if not _check_initiate_message.is_running():
        try:
            # 루프 함수에 bot 인스턴스 전달
            _check_initiate_message.start(bot)
            logger.info("Initiate checker task started.")
            return _check_initiate_message
        except Exception as e:
            logger.exception("Failed to start initiate checker task:")
            return None
    else:
        logger.warning("Initiate checker task is already running.")
        return _check_initiate_message

def stop_initiate_checker():
    """선톡 검사 루프를 중지합니다."""
    if _check_initiate_message.is_running():
        _check_initiate_message.stop()
        logger.info("Initiate checker task stopped.")
