import asyncio
import logging
import sys
import os

# 프로젝트 루트를 sys.path에 추가 (다른 모듈 임포트 위함)
# current_dir = os.path.dirname(os.path.abspath(__file__))
# sys.path.append(current_dir)

import config # 먼저 config를 임포트하여 환경변수 로드 및 설정 적용
from bot.client import KiyoBot # 봇 클라이언트 클래스 임포트
from web.server import start_web_server # 웹 서버 시작 함수 임포트

# --- 로깅 설정 ---
# 기본 로깅 설정
logging.basicConfig(
    level=config.LOG_LEVEL,
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 라이브러리 로깅 레벨 조정 (필요시 주석 해제)
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("discord.http").setLevel(logging.WARNING)
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
logging.getLogger("discord.client").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.INFO) # asyncio 디버깅 필요시 DEBUG로 변경
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
# logging.getLogger("openai").setLevel(logging.INFO) # OpenAI API 호출 로그 확인시

# 루트 로거 설정
logger = logging.getLogger(__name__)

# --- 메인 실행 함수 ---
async def main():
    """애플리케이션 메인 실행 함수"""
    logger.info("Initializing Kiyo Bot...")

    if not config.DISCORD_BOT_TOKEN:
        logger.critical("Discord bot token not found in environment variables. Exiting.")
        sys.exit(1) # 토큰 없으면 종료

    # 봇 인스턴스 생성
    bot = KiyoBot()

    # 비동기 작업 실행 (봇, 웹서버)
    # 웹서버는 선택사항이므로, 필요 없다면 gather에서 제외 가능
    tasks = [
        bot.start_bot(), # 봇 시작
        start_web_server() # 웹 서버 시작
    ]

    await asyncio.gather(*tasks)

# --- 스크립트 실행 ---
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt).")
    except Exception as e:
        logger.critical(f"An unexpected error occurred: {e}", exc_info=True)
        sys.exit(1) # 예상치 못한 오류 발생 시 종료
