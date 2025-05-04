# config.py
import os
import logging
from dotenv import load_dotenv
import pytz
from discord import Intents

# .env 파일 로드 (파일이 없어도 오류 없이 진행)
load_dotenv()

# --- 필수 환경 변수 ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
USER_DISCORD_NAME = os.getenv("USER_DISCORD_NAME")
USER_ID = int(os.getenv("USER_ID")) if os.getenv("USER_ID") else None
NOTION_DIARY_DB_ID = os.getenv("NOTION_DIARY_DB_ID")
NOTION_OBSERVATION_DB_ID = os.getenv("NOTION_OBSERVATION_DB_ID")
NOTION_MEMORY_DB_ID = os.getenv("NOTION_MEMORY_DB_ID")
NOTION_TODO_DB_ID = os.getenv("NOTION_TODO_DB_ID")
MIDJOURNEY_BOT_ID = int(os.getenv("MIDJOURNEY_BOT_ID")) if os.getenv("MIDJOURNEY_BOT_ID") else None

# --- 선택적 환경 변수 (기본값 설정) ---
DISCORD_SERVER_NAME = os.getenv("DISCORD_SERVER_NAME", "SNKY") # Midjourney 서버 이름 기본값
MIDJOURNEY_CHANNEL_NAME = os.getenv("MIDJOURNEY_CHANNEL_NAME", "midjourney-image-channel")
USE_SILLYTAVERN = os.getenv("USE_SILLYTAVERN_API", "false").lower() == "true"
SILLYTAVERN_API_BASE = os.getenv("SILLYTAVERN_API_BASE", "http://localhost:8000/v1")
WEB_SERVER_PORT = int(os.getenv("PORT", 10000)) # 웹 서버 포트

# --- 필수 설정 값 검증 ---
required_vars = {
    "DISCORD_BOT_TOKEN": DISCORD_BOT_TOKEN,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "NOTION_TOKEN": NOTION_TOKEN,
    "USER_DISCORD_NAME": USER_DISCORD_NAME,
    "USER_ID": USER_ID,
    "NOTION_DIARY_DB_ID": NOTION_DIARY_DB_ID,
    "NOTION_OBSERVATION_DB_ID": NOTION_OBSERVATION_DB_ID,
    "NOTION_MEMORY_DB_ID": NOTION_MEMORY_DB_ID,
    "NOTION_TODO_DB_ID": NOTION_TODO_DB_ID,
    "MIDJOURNEY_BOT_ID": MIDJOURNEY_BOT_ID,
}

missing_vars = [name for name, value in required_vars.items() if value is None]
if missing_vars:
    logging.error(f"오류: 필수 환경변수가 설정되지 않았습니다: {', '.join(missing_vars)}")
    raise ValueError(f"필수 환경변수 누락: {', '.join(missing_vars)}")

# --- 상수 ---
KST = pytz.timezone("Asia/Seoul")
NOTION_API_VERSION = "2022-06-28"
FACE_TO_FACE_CHANNEL_ID = 1362310907711197194 # 예시 ID, 실제 ID로 변경 필요
INITIATE_CHECK_INTERVAL_MINUTES = 30 # 선톡 체크 간격 (분)
INITIATE_CHECK_START_HOUR = 11 # 선톡 가능 시작 시간 (KST)
INITIATE_CHECK_END_HOUR = 1  # 선톡 가능 종료 시간 (KST, 다음날 새벽 1시)
MIN_INACTIVE_HOURS_FOR_INITIATE = 12 # 선톡 발동 최소 비활성 시간 (시간)
CONVERSATION_LOG_MAX_LENGTH = 20 # 메모리에 유지할 대화 기록 최대 길이
GPT_MODEL = "gpt-4o" # 사용할 GPT 모델

# --- Discord Intents ---
intents = Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True # 멤버 관련 이벤트 처리 시 필요
intents.presences = False # Presence 정보 불필요 시 False로 설정 권장

# --- Notion 클라이언트 헤더 ---
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_API_VERSION,
    "Content-Type": "application/json"
}

# --- 로깅 설정 ---
LOG_LEVEL = logging.INFO # 운영 시 INFO, 개발 시 DEBUG
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 라이브러리 로깅 레벨 조정 (노이즈 감소)
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
logging.getLogger("discord.client").setLevel(logging.WARNING)
logging.getLogger("discord.http").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

# --- 감정 및 태그 (기존 notion_utils.py에서 이동) ---
EMOTION_TAGS = {
    "자신감": ["고요", "자부심"],
    "불안": ["혼란", "불확실성"],
    "애정_서영": ["연애", "애정", "의존"],
    "불만_서영": ["질투", "분노", "소외감"],
    "망상": ["집착", "환각", "해석"],
    "기록": ["중립", "관찰"]
}

OBSERVATION_TAGS = [
    "불안", "긴장", "집착", "거리감", "다정함", "무력감", "이해", # 감정 기반
    "기록", "분석", "의심", "몰입", "추론", "판단 보류", # 관찰 태도 기반
    "의례", "금기", "상징", "무의식", "기억", "신화화" # 민속학자 관점 기반
]

MJ_STYLE_SUFFIX = ( # Midjourney 프롬프트 스타일 접미사
    "unprofessional photography, expired kodak gold 200, 35mm film, candid snapshot, "
    "imperfect framing, soft focus, light grain, slightly overexposed, amateur aesthetic, "
    "mundane photo, low saturation, motion blur, poorly exposed, flash glare, low fidelity"
)
