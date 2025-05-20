import os
import logging
from zoneinfo import ZoneInfo # python 3.9+
# from pytz import timezone # python 3.8 이하 또는 pytz 선호시
from dotenv import load_dotenv
from datetime import timezone as tz_utc, timedelta # Fallback용
from typing import Optional, List, Dict # 타입 힌트용 추가

# .env 파일 로드 (파일이 없어도 오류 발생 안 함)
load_dotenv()

# --- 기본 설정 ---
BOT_PREFIX = "!"
LOG_LEVEL = logging.getLevelName(os.getenv("LOG_LEVEL", "INFO").upper())
try:
    KST = ZoneInfo("Asia/Seoul")
    logging.info("Using zoneinfo for KST.")
except Exception:
    try:
        from pytz import timezone
        KST = timezone("Asia/Seoul")
        logging.info("Using pytz for KST.")
    except ImportError:
        logging.error("Neither zoneinfo nor pytz is available. Using UTC+9 fallback.")
        KST = tz_utc(timedelta(hours=9), name="KST")

# --- Discord 설정 ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not DISCORD_BOT_TOKEN:
    logging.critical("환경변수 'DISCORD_BOT_TOKEN'이 설정되지 않았습니다. 봇을 시작할 수 없습니다.")

TARGET_USER_ID_STR = os.getenv("USER_ID") # 문자열로 먼저 받음
TARGET_USER_ID: Optional[int] = None      # 정수 타입으로 변환 후 저장할 변수
if TARGET_USER_ID_STR:
    try:
        TARGET_USER_ID = int(TARGET_USER_ID_STR)
    except ValueError:
        logging.error(f"환경변수 'USER_ID'({TARGET_USER_ID_STR})가 올바른 숫자 형식이 아닙니다.")
else:
    logging.warning("환경변수 'USER_ID'가 설정되지 않았습니다. 일부 기능이 제한될 수 있습니다.")

TARGET_USER_DISCORD_NAME = os.getenv("USER_DISCORD_NAME")
if not TARGET_USER_DISCORD_NAME and not TARGET_USER_ID: # 둘 다 없으면 문제
    logging.error("환경변수 'USER_ID' 또는 'USER_DISCORD_NAME' 중 하나는 설정해야 합니다.")


# --- Midjourney 설정 ---
MIDJOURNEY_SERVER_NAME = os.getenv("DISCORD_SERVER_NAME", "SNKY")
MIDJOURNEY_CHANNEL_NAME = os.getenv("MIDJOURNEY_CHANNEL_NAME", "midjourney-image-channel")
MIDJOURNEY_BOT_ID_STR = os.getenv("MIDJOURNEY_BOT_ID")
MIDJOURNEY_BOT_ID: Optional[int] = None
if MIDJOURNEY_BOT_ID_STR:
    try:
        MIDJOURNEY_BOT_ID = int(MIDJOURNEY_BOT_ID_STR)
    except ValueError:
        logging.error(f"환경변수 'MIDJOURNEY_BOT_ID'({MIDJOURNEY_BOT_ID_STR})가 올바른 숫자 형식이 아닙니다.")
else:
    logging.warning("환경변수 'MIDJOURNEY_BOT_ID'가 설정되지 않았습니다. Midjourney 연동 기능이 제한될 수 있습니다.")

MIDJOURNEY_STYLE_SUFFIX = (
    "unprofessional photography, expired kodak gold 200, 35mm film, candid snapshot, "
    "imperfect framing, soft focus, light grain, slightly overexposed, amateur aesthetic, "
    "mundane photo, low saturation, motion blur, poorly exposed, flash glare, low fidelity"
)
MIDJOURNEY_DEFAULT_AR = "--ar 3:2"

# --- Notion 설정 ---
NOTION_API_KEY = os.getenv("NOTION_TOKEN")
if not NOTION_API_KEY:
    logging.critical("환경변수 'NOTION_TOKEN'이 설정되지 않았습니다. Notion 연동이 불가능합니다.")

NOTION_API_VERSION = "2022-06-28"

# 각 Notion 데이터베이스 ID
NOTION_DIARY_DB_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_OBSERVATION_DB_ID = os.getenv("NOTION_OBSERVATION_DB_ID")
NOTION_MEMORY_DB_ID = os.getenv("NOTION_MEMORY_DB_ID")
NOTION_TODO_DB_ID = os.getenv("TODO_DATABASE_ID")
# <<< 새로운 스케줄 DB ID 추가 >>>
NOTION_SCHEDULE_DB_ID = os.getenv("NOTION_SCHEDULE_ID") # .env 파일의 키 이름과 일치

# DB ID 로딩 확인
db_ids_to_check = {
    "Diary DB": NOTION_DIARY_DB_ID,
    "Observation DB": NOTION_OBSERVATION_DB_ID,
    "Memory DB": NOTION_MEMORY_DB_ID,
    "ToDo DB": NOTION_TODO_DB_ID,
    "Schedule DB": NOTION_SCHEDULE_DB_ID # <<< 확인 목록에 추가 >>>
}
missing_db_ids = [name for name, db_id in db_ids_to_check.items() if not db_id]
if missing_db_ids:
    logging.warning(f"다음 Notion 데이터베이스 ID 환경변수가 설정되지 않았습니다: {', '.join(missing_db_ids)}. 관련 기능이 제한될 수 있습니다.")


# --- OpenAI / LLM 설정 ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logging.warning("환경변수 'OPENAI_API_KEY'가 설정되지 않았습니다. AI 기능이 제한됩니다.")

USE_SILLYTAVERN = os.getenv("USE_SILLYTAVERN_API", "false").lower() == "true"
SILLYTAVERN_API_BASE = os.getenv("SILLYTAVERN_API_BASE", "http://127.0.0.1:5001/v1")
SILLYTAVERN_MODEL_NAME = os.getenv("SILLYTAVERN_MODEL_NAME", "gpt-4o")

DEFAULT_LLM_MODEL = "gpt-4o"

# --- 기능별 설정 ---
INITIATE_CHECK_INTERVAL_MINUTES = int(os.getenv("INITIATE_CHECK_INTERVAL_MINUTES", 480)) # 기본값 8시간 (480분)
INITIATE_ALLOWED_START_HOUR = int(os.getenv("INITIATE_ALLOWED_START_HOUR", 11))
INITIATE_ALLOWED_END_HOUR = int(os.getenv("INITIATE_ALLOWED_END_HOUR", 1))
INITIATE_MIN_GAP_HOURS = int(os.getenv("INITIATE_MIN_GAP_HOURS", 24)) # 기본값 24시간

FACE_TO_FACE_CHANNEL_ID_STR = os.getenv("FACE_TO_FACE_CHANNEL_ID")
FACE_TO_FACE_CHANNEL_ID: Optional[int] = None
if FACE_TO_FACE_CHANNEL_ID_STR:
    try:
        FACE_TO_FACE_CHANNEL_ID = int(FACE_TO_FACE_CHANNEL_ID_STR)
    except ValueError:
        logging.error(f"환경변수 'FACE_TO_FACE_CHANNEL_ID'({FACE_TO_FACE_CHANNEL_ID_STR})가 올바른 숫자 형식이 아닙니다.")

# --- <<< 새로운 키요 감정 변화 관련 설정 추가 >>> ---
# 감정 변화 체크 주기 (단위: 초). 기본값: 30분 (1800초)
KIYO_EMOTION_DECAY_CHECK_INTERVAL_SECONDS = int(os.getenv("KIYO_EMOTION_DECAY_CHECK_INTERVAL_SECONDS", 60 * 30))

# 감정 변화가 발동되는 최소 비활성 시간 (단위: 초). 기본값: 3시간 (10800초)
KIYO_EMOTION_CHANGE_INACTIVITY_THRESHOLD_SECONDS = int(os.getenv("KIYO_EMOTION_CHANGE_INACTIVITY_THRESHOLD_SECONDS", 3 * 60 * 60))

# (선택적) 감정 자동 변경 시 사용자에게 내적 독백 형태의 DM을 보낼지 여부 (True/False)
# .env 파일에서 "true" 또는 "false" 문자열로 설정 가능
SEND_EMOTION_CHANGE_MONOLOGUE_STR = os.getenv("SEND_EMOTION_CHANGE_MONOLOGUE", "false").lower()
SEND_EMOTION_CHANGE_MONOLOGUE = SEND_EMOTION_CHANGE_MONOLOGUE_STR == "true"

# --- 웹 서버 설정 ---
WEB_SERVER_PORT = int(os.getenv("PORT", 10000))
WEB_SERVER_HOST = os.getenv("HOST", "0.0.0.0")


# --- 유틸리티 상수 ---
EMOTION_TAGS: Dict[str, List[str]] = {
    "슬픔": ["슬픔", "우울", "상실감"], "애정": ["애정", "연애", "그리움", "행복"],
    "불만_분노": ["분노", "짜증", "질투", "실망", "미움"], "혼란_망상": ["혼란", "망상", "모호함", "비현실"],
    "긍정_안정": ["안정", "감사", "만족", "평온"], "불안": ["불안", "걱정", "긴장", "두려움"],
    "중립_기록": ["기록", "관찰", "중립", "사실"]
}

OBSERVATION_TAGS: List[str] = [
    "불안", "긴장", "집착", "거리감", "다정함", "무력감", "이해",
    "기록", "분석", "의심", "몰입", "추론", "판단 보류",
    "의례", "금기", "상징", "무의식", "기억", "신화화"
]

# Notion "요일" 속성 옵션과 일치해야 함 (tasks/scheduler.py, services/notion_service.py 등에서 사용 가능하도록)
korean_weekday_map: List[str] = ["월", "화", "수", "목", "금", "토", "일"]
