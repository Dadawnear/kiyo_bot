import os
import logging
from zoneinfo import ZoneInfo # python 3.9+
# from pytz import timezone # python 3.8 이하 또는 pytz 선호시
from dotenv import load_dotenv

# .env 파일 로드 (파일이 없어도 오류 발생 안 함)
load_dotenv()

# --- 기본 설정 ---
BOT_PREFIX = "!"
LOG_LEVEL = logging.getLevelName(os.getenv("LOG_LEVEL", "INFO").upper()) # DEBUG, INFO, WARNING, ERROR
# 타임존 설정 (Python 3.9 이상 ZoneInfo 권장)
try:
    KST = ZoneInfo("Asia/Seoul")
except Exception:
    # Pytz fallback 또는 오류 처리
    try:
        from pytz import timezone
        KST = timezone("Asia/Seoul")
        logging.info("Using pytz for timezone.")
    except ImportError:
        logging.error("Neither zoneinfo nor pytz is available. Please install pytz (`pip install pytz`) or ensure Python 3.9+.")
        # 기본 UTC라도 설정하거나 종료
        from datetime import timezone as tz_utc, timedelta
        KST = tz_utc(timedelta(hours=9), name="KST")


# --- Discord 설정 ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not DISCORD_BOT_TOKEN:
    logging.error("환경변수 'DISCORD_BOT_TOKEN'이 설정되지 않았습니다.")
    # raise ValueError("DISCORD_BOT_TOKEN is not set.") # 필요시 프로그램 강제 종료

# 상호작용할 유저 설정
TARGET_USER_ID = os.getenv("USER_ID")
if TARGET_USER_ID:
    try:
        TARGET_USER_ID = int(TARGET_USER_ID)
    except ValueError:
        logging.error(f"환경변수 'USER_ID'({TARGET_USER_ID})가 올바른 숫자 형식이 아닙니다.")
        TARGET_USER_ID = None
else:
    logging.warning("환경변수 'USER_ID'가 설정되지 않았습니다. 일부 기능이 제한될 수 있습니다.")

TARGET_USER_DISCORD_NAME = os.getenv("USER_DISCORD_NAME") # 예: "username#1234"
if not TARGET_USER_DISCORD_NAME:
    logging.warning("환경변수 'USER_DISCORD_NAME'이 설정되지 않았습니다. 일부 기능이 제한될 수 있습니다.")

# --- Midjourney 설정 ---
MIDJOURNEY_SERVER_NAME = os.getenv("DISCORD_SERVER_NAME", "SNKY") # Midjourney가 있는 서버 이름
MIDJOURNEY_CHANNEL_NAME = os.getenv("MIDJOURNEY_CHANNEL_NAME", "midjourney-image-channel") # Midjourney 이미지 채널 이름
MIDJOURNEY_BOT_ID = os.getenv("MIDJOURNEY_BOT_ID")
if MIDJOURNEY_BOT_ID:
    try:
        MIDJOURNEY_BOT_ID = int(MIDJOURNEY_BOT_ID)
    except ValueError:
        logging.error(f"환경변수 'MIDJOURNEY_BOT_ID'({MIDJOURNEY_BOT_ID})가 올바른 숫자 형식이 아닙니다.")
        MIDJOURNEY_BOT_ID = None
else:
    logging.warning("환경변수 'MIDJOURNEY_BOT_ID'가 설정되지 않았습니다. Midjourney 연동 기능이 제한될 수 있습니다.")

MIDJOURNEY_STYLE_SUFFIX = ( # 기본 제공 스타일
    "unprofessional photography, expired kodak gold 200, 35mm film, candid snapshot, "
    "imperfect framing, soft focus, light grain, slightly overexposed, amateur aesthetic, "
    "mundane photo, low saturation, motion blur, poorly exposed, flash glare, low fidelity"
)
MIDJOURNEY_DEFAULT_AR = "--ar 3:2"

# --- Notion 설정 ---
NOTION_API_KEY = os.getenv("NOTION_TOKEN")
if not NOTION_API_KEY:
    logging.error("환경변수 'NOTION_TOKEN'이 설정되지 않았습니다.")

NOTION_API_VERSION = "2022-06-28"

# 각 Notion 데이터베이스 ID
NOTION_DIARY_DB_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_OBSERVATION_DB_ID = os.getenv("NOTION_OBSERVATION_DB_ID")
NOTION_MEMORY_DB_ID = os.getenv("NOTION_MEMORY_DB_ID")
NOTION_TODO_DB_ID = os.getenv("TODO_DATABASE_ID")

if not all([NOTION_DIARY_DB_ID, NOTION_OBSERVATION_DB_ID, NOTION_MEMORY_DB_ID, NOTION_TODO_DB_ID]):
    logging.warning("하나 이상의 Notion 데이터베이스 ID 환경변수가 설정되지 않았습니다. Notion 연동 기능이 제한될 수 있습니다.")

# Notion API 헤더 (Notion 서비스에서 사용)
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": NOTION_API_VERSION,
    "Content-Type": "application/json"
}


# --- OpenAI / LLM 설정 ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logging.warning("환경변수 'OPENAI_API_KEY'가 설정되지 않았습니다. SillyTavern 사용 또는 AI 기능 제한됩니다.")

# SillyTavern 설정 (선택 사항)
USE_SILLYTAVERN = os.getenv("USE_SILLYTAVERN_API", "false").lower() == "true"
SILLYTAVERN_API_BASE = os.getenv("SILLYTAVERN_API_BASE", "http://127.0.0.1:5001/v1") # 기본 로컬 주소로 변경
SILLYTAVERN_MODEL_NAME = os.getenv("SILLYTAVERN_MODEL_NAME", "gpt-4o") # SillyTavern에서 사용할 모델

# 사용할 기본 LLM 모델
DEFAULT_LLM_MODEL = "gpt-4o" # OpenAI 사용 시 기본 모델

# --- 기능별 설정 ---
# 선톡 기능 설정
INITIATE_CHECK_INTERVAL_MINUTES = 30
INITIATE_ALLOWED_START_HOUR = 11 # 선톡 시작 시간 (KST)
INITIATE_ALLOWED_END_HOUR = 1   # 선톡 종료 시간 (KST, 다음날 새벽)
INITIATE_MIN_GAP_HOURS = 12     # 최소 공백 시간 (이 시간 미만이면 선톡 안 함)

# 대면 채널 ID (특수 로직 적용)
FACE_TO_FACE_CHANNEL_ID = os.getenv("FACE_TO_FACE_CHANNEL_ID")
if FACE_TO_FACE_CHANNEL_ID:
    try:
        FACE_TO_FACE_CHANNEL_ID = int(FACE_TO_FACE_CHANNEL_ID)
    except ValueError:
        logging.error(f"환경변수 'FACE_TO_FACE_CHANNEL_ID'({FACE_TO_FACE_CHANNEL_ID})가 올바른 숫자 형식이 아닙니다.")
        FACE_TO_FACE_CHANNEL_ID = None


# --- 웹 서버 설정 ---
WEB_SERVER_PORT = int(os.getenv("PORT", 10000)) # Render 등 호스팅 플랫폼 기본 포트
WEB_SERVER_HOST = "0.0.0.0"


# --- 유틸리티 상수 (utils/constants.py로 옮겨도 무방) ---
EMOTION_TAGS = { # 노션 일기 자동 태그용
    "자신감": ["고요", "자부심"],
    "불안": ["혼란", "불확실성"],
    "애정_서영": ["연애", "애정", "의존"],
    "불만_서영": ["질투", "분노", "소외감"],
    "망상": ["집착", "환각", "해석"],
    "기록": ["중립", "관찰"]
}

OBSERVATION_TAGS = [ # 노션 관찰일지 자동 태그용
    # 🎭 감정 기반
    "불안", "긴장", "집착", "거리감", "다정함", "무력감", "이해",
    # 🔍 관찰 태도 기반
    "기록", "분석", "의심", "몰입", "추론", "판단 보류",
    # 🧿 민속학자 관점 기반
    "의례", "금기", "상징", "무의식", "기억", "신화화"
]

# 설정값 로딩 확인 로그 (필요시 활성화)
# logging.debug(f"Config loaded: TARGET_USER_ID={TARGET_USER_ID}, NOTION_DIARY_DB_ID={NOTION_DIARY_DB_ID}, etc.")
