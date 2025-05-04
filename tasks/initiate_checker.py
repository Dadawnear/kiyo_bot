import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

import discord
from discord.ext import tasks, commands # commands.Bot 타입 힌트용

import config # 설정 임포트
from utils.activity_tracker import get_last_active # 마지막 활동 시간 유틸리티

# --- Service Imports ---
# 실제 서비스 클래스 임포트
from services.ai_service import AIService
from services.notion_service import NotionService

# 타입 힌트를 위해 KiyoBot 클래스 임포트 (순환 참조 방지)
if TYPE_CHECKING:
    from bot.client import KiyoBot

logger = logging.getLogger(__name__)

# --- Tasks Loop Definition ---

# tasks.loop 데코레이터를 사용하여 주기적 실행 함수 정의
# loop 간격은 config 파일에서 가져옴
@tasks.loop(minutes=config.INITIATE_CHECK_INTERVAL_MINUTES)
async def _check_initiate_message_loop(bot: 'KiyoBot'):
    """주기적으로 실행되어 선톡 조건을 확인하고 메시지를 보냅니다."""
    # 루프가 실행될 때마다 현재 시간 가져오기
    now = datetime.now(config.KST)
    current_hour = now.hour
    logger.debug(f"[Initiate Check] Running check at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    # 0. 설정 값 확인
    if not config.TARGET_USER_ID:
        logger.warning("[Initiate Check] TARGET_USER_ID가 설정되지 않아 선톡 기능을 중지합니다.")
        _check_initiate_message_loop.cancel() # 루프 영구 중지
        return

    # 1. 허용 시간대 확인
    start_h = config.INITIATE_ALLOWED_START_HOUR
    end_h = config.INITIATE_ALLOWED_END_HOUR
    is_allowed_time = False
    if start_h <= end_h: # 같은 날 (예: 11시 ~ 18시)
        if start_h <= current_hour < end_h: is_allowed_time = True
    else: # 다음 날로 넘어가는 경우 (예: 23시 ~ 01시)
        if current_hour >= start_h or current_hour < end_h: is_allowed_time = True

    if not is_allowed_time:
        logger.debug(f"[Initiate Check] Not within allowed time window ({start_h:02d}:00 - {end_h:02d}:00 KST). Skipping.")
        return

    # 서비스 인스턴스 가져오기
    ai_service: AIService = bot.ai_service
    notion_service: NotionService = bot.notion_service

    try:
        # 2. 대상 유저 정보 가져오기
        user = await bot.fetch_user(config.TARGET_USER_ID)
        # user가 None이면 아래 로직에서 오류 발생하므로 여기서 처리
        if not user:
            logger.warning(f"[Initiate Check] Target user ID {config.TARGET_USER_ID} not found.")
            return

        # 3. 마지막 활동 시간 확인
        last_active_time = get_last_active() # utils.activity_tracker 사용
        if not last_active_time:
            logger.info("[Initiate Check] No last active time recorded yet. Skipping.")
            return

        # 4. 비활성 시간 계산 및 확인
        time_gap = now - last_active_time
        gap_hours = time_gap.total_seconds() / 3600
        logger.debug(f"[Initiate Check] Last active: {last_active_time.strftime('%Y-%m-%d %H:%M:%S %Z')}, Gap: {gap_hours:.2f} hours.")

        min_gap = config.INITIATE_MIN_GAP_HOURS
        if gap_hours < min_gap:
            logger.debug(f"[Initiate Check] Time gap ({gap_hours:.2f} hrs) < minimum ({min_gap} hrs). Skipping.")
            return

        # --- 선톡 조건 만족, 메시지 생성 및 전송 ---
        logger.info(f"[Initiate Check] Conditions met for user {user.id}. Generating message...")

        # 5. 컨텍스트 수집 (Notion 서비스 사용)
        past_memories = await notion_service.fetch_recent_memories(limit=3)
        past_obs = await notion_service.fetch_recent_observations(limit=1)

        # 6. AI 서비스로 메시지 생성
        initiate_message = await ai_service.generate_initiate_message(
            gap_hours=gap_hours,
            past_memories=past_memories if isinstance(past_memories, list) else None,
            past_obs=past_obs if isinstance(past_obs, str) else None
        )

        if not initiate_message or initiate_message == "...":
            logger.warning("[Initiate Check] Failed to generate initiate message or got default response.")
            return

        # 7. 사용자 DM 채널 가져와서 메시지 전송
        dm_channel = user.dm_channel or await user.create_dm()
        if not dm_channel:
             logger.error(f"[Initiate Check] Could not get or create DM channel for user {user.id}")
             return

        await dm_channel.send(initiate_message)
        logger.info(f"[Initiate Check] Sent initiate message to user {user.id} after {gap_hours:.2f} hours of inactivity: '{initiate_message[:50]}...'")

        # 선톡 후 마지막 활동 시간 업데이트 (선택적)
        # update_last_active()

    except discord.NotFound:
         logger.warning(f"[Initiate Check] Target user ID {config.TARGET_USER_ID} not found during operation.")
    except discord.Forbidden:
         logger.error("[Initiate Check] Missing permissions to fetch user or send DM. Check bot permissions.")
         # 권한 문제 시 루프 자동 중지될 수 있음 (오류 계속 발생 시)
    except Exception as e:
        # Notion API 오류 등 다른 서비스 오류 포함
        logger.error(f"[Initiate Check] Error during check: {e}", exc_info=True)


@_check_initiate_message_loop.before_loop
async def before_initiate_check():
    """루프 시작 전 봇이 준비될 때까지 기다립니다."""
    # 이 함수는 bot 객체를 직접 받지 못하므로, 시작하는 쪽에서 wait_until_ready를 호출해야 합니다.
    # 여기서는 단순히 로그만 남기거나, bot 객체에 접근할 방법(예: 클래스 멤버)이 있다면 사용합니다.
    # 여기서는 setup_hook에서 bot.wait_until_ready 후에 이 루프를 시작한다고 가정합니다.
    logger.info("Initiate checker loop starting...")


# --- Task Control Functions ---

_initiate_checker_task_obj: Optional[tasks.Loop] = None

def start_initiate_checker(bot: 'KiyoBot') -> Optional[tasks.Loop]:
    """
    선톡 검사 루프를 시작합니다. bot/client.py의 setup_hook에서 호출됩니다.

    Args:
        bot: KiyoBot 인스턴스.

    Returns:
        시작된 tasks.Loop 객체 또는 실패 시 None.
    """
    global _initiate_checker_task_obj
    if _check_initiate_message_loop.is_running():
        logger.warning("Initiate checker task is already running.")
        return _initiate_checker_task_obj

    if not config.TARGET_USER_ID:
         logger.warning("Cannot start initiate checker: TARGET_USER_ID is not set.")
         return None

    try:
        # 루프 함수에 bot 인스턴스 전달하여 시작
        _check_initiate_message_loop.start(bot)
        _initiate_checker_task_obj = _check_initiate_message_loop
        logger.info("Initiate checker task started successfully.")
        return _initiate_checker_task_obj
    except Exception as e:
        logger.exception("Failed to start initiate checker task:")
        return None

def stop_initiate_checker():
    """선톡 검사 루프를 중지합니다."""
    global _initiate_checker_task_obj
    if _check_initiate_message_loop.is_running():
        _check_initiate_message_loop.cancel() # cancel() 사용 권장
        # _check_initiate_message_loop.stop() # stop은 다음 반복 전에 멈춤
        logger.info("Initiate checker task stopped.")
        _initiate_checker_task_obj = None
    else:
        logger.info("Initiate checker task is not running.")
