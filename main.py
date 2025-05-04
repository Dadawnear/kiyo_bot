import asyncio
import logging
import sys
import os
import signal # 종료 시그널 처리 위해 추가
from typing import Optional 
import aiohttp

# 프로젝트 루트를 sys.path에 추가 (필요한 경우 주석 해제)
# current_dir = os.path.dirname(os.path.abspath(__file__))
# sys.path.append(current_dir)

import config # 설정 로드
from bot.client import KiyoBot # 봇 클래스 임포트
from web.server import start_web_server # 웹 서버 시작 함수 임포트

# --- 로깅 설정 ---
logging.basicConfig(
    level=config.LOG_LEVEL,
    format='%(asctime)s [%(levelname)-8s] [%(name)-15s] %(message)s', # 포맷 약간 수정
    datefmt='%Y-%m-%d %H:%M:%S'
)
# 라이브러리 로깅 레벨 조정 (필요한 라이브러리만)
logging.getLogger("discord").setLevel(logging.INFO) # discord 로깅 레벨 INFO로 조정 (필요시 WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

# 루트 로거
logger = logging.getLogger(__name__)

# --- 글로벌 변수 (봇 인스턴스, 웹 서버 러너) ---
# 종료 핸들러에서 접근하기 위해
bot_instance: Optional[KiyoBot] = None
web_runner: Optional[aiohttp.web.AppRunner] = None

# --- 종료 처리 핸들러 ---
async def shutdown(signal, loop):
    """종료 시그널 수신 시 실행될 핸들러"""
    logger.warning(f"Received exit signal {signal.name}... Shutting down.")

    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    # 모든 태스크 취소 요청
    # [t.cancel() for t in tasks]
    # logger.info(f"Cancelling {len(tasks)} outstanding tasks...")
    # await asyncio.gather(*tasks, return_exceptions=True) # 취소 완료 기다림

    # 봇 종료 (리소스 정리 포함)
    if bot_instance and not bot_instance.is_closed():
        await bot_instance.close()

    # 웹 서버 정리
    if web_runner:
        await web_runner.cleanup()
        logger.info("Web server runner cleaned up.")

    # 이벤트 루프 중지
    loop.stop()

# --- 메인 실행 함수 ---
async def main():
    """애플리케이션 메인 실행 함수"""
    global bot_instance, web_runner
    logger.info("Initializing Kiyo Bot application...")

    loop = asyncio.get_running_loop()

    # 종료 시그널(SIGINT: Ctrl+C, SIGTERM: kill) 핸들러 등록
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        # loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown(s, loop)))
        # signal 핸들러는 동기 함수여야 할 수 있음
         loop.add_signal_handler(s, lambda s=s: asyncio.ensure_future(shutdown(s, loop)))


    try:
        # 봇 인스턴스 생성
        bot_instance = KiyoBot()

        # 웹 서버 시작 및 runner 객체 받기
        web_runner = await start_web_server()

        # 봇 시작 (start_bot 내부에 루프 및 종료 처리 포함)
        await bot_instance.start_bot()

    except RuntimeError as e: # 예: 서비스 초기화 실패
         logger.critical(f"Application failed to start: {e}")
         # 필요한 추가 정리 작업?
    except Exception as e:
        logger.critical(f"An unexpected error occurred in main: {e}", exc_info=True)
    finally:
        logger.info("Main function finished.")
        # 루프가 stop()으로 멈추면 여기서 추가 정리 작업 가능
        # loop.close() # run_forever 사용 시 필요할 수 있음


# --- 스크립트 실행 ---
if __name__ == "__main__":
    # 로깅 기본 설정 위치 이동 (import 후 바로 설정되도록)
    # logging.basicConfig(...)
    try:
        # 이벤트 루프 생성 및 실행
        # asyncio.run(main()) # run은 내부적으로 새 루프 생성 및 종료 시 close 호출

        # 시그널 핸들러와 함께 사용 시 run_forever 사용 고려
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
        # loop.run_forever() # shutdown에서 loop.stop() 호출 시 종료됨

    except KeyboardInterrupt:
        logger.info("Application stopped by user (KeyboardInterrupt in main).")
    finally:
         logger.info("Application exiting.")
         # 루프 종료 (run_forever 사용 시)
         # loop = asyncio.get_event_loop()
         # if loop.is_running(): loop.stop()
         # if not loop.is_closed(): loop.close()
