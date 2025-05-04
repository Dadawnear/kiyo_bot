import logging
from datetime import datetime
import config # 설정 파일 임포트 (KST 타임존 사용 위해)

logger = logging.getLogger(__name__)

# 모듈 레벨에서 마지막 활동 시간 저장 (봇 실행 시점 기준으로 초기화)
# 다중 사용자 환경에서는 이 방식 수정 필요 (예: 딕셔너리로 사용자별 관리)
_last_user_active_time: datetime = datetime.now(config.KST)
logger.debug(f"Activity tracker initialized. Initial time set to: {_last_user_active_time}")

def update_last_active():
    """대상 사용자의 마지막 활동 시간을 현재 시간으로 갱신합니다."""
    global _last_user_active_time
    _last_user_active_time = datetime.now(config.KST)
    # 디버그 레벨이 너무 빈번할 수 있으므로 필요시에만 활성화
    # logger.debug(f"User activity time updated to: {_last_user_active_time}")

def get_last_active() -> datetime:
    """마지막으로 기록된 사용자 활동 시간을 반환합니다."""
    # logger.debug(f"Retrieving last active time: {_last_user_active_time}")
    return _last_user_active_time

# get_last_user_message_time 함수는 get_last_active와 동일하므로 제거하거나 유지 가능
# def get_last_user_message_time():
#     return get_last_active()
