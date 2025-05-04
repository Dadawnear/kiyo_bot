import logging
from aiohttp import web

import config # 설정 파일 임포트 (포트, 호스트 정보 사용)

logger = logging.getLogger(__name__)

# --- Request Handlers ---

async def handle_root(request: web.Request) -> web.Response:
    """루트 URL('/') 요청 처리"""
    logger.debug("Received request for /")
    # 간단한 환영 메시지 또는 봇 상태 정보 제공 가능
    text = f"Kiyo Discord Bot is running. (Current time: {datetime.now(config.KST).strftime('%Y-%m-%d %H:%M:%S %Z')})"
    return web.Response(text=text, content_type="text/plain")

async def handle_health(request: web.Request) -> web.Response:
    """헬스 체크 URL('/health') 요청 처리"""
    logger.debug("Received request for /health")
    # 호스팅 플랫폼의 헬스 체크용 응답
    # 필요하다면 봇의 내부 상태 (로그인 여부, 지연 시간 등)를 확인하여
    # 더 구체적인 상태 코드 (예: 503 Service Unavailable) 반환 가능
    return web.Response(text="OK", content_type="text/plain")

# --- Web Server Setup ---

async def start_web_server():
    """aiohttp 웹 서버를 설정하고 시작합니다."""
    app = web.Application()

    # 라우터 설정
    app.router.add_get("/", handle_root)
    app.router.add_get("/health", handle_health)
    # 필요시 다른 엔드포인트 추가 가능 (예: 봇 상태 API)

    # AppRunner 및 TCPSite 설정
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=config.WEB_SERVER_HOST, port=config.WEB_SERVER_PORT)

    try:
        await site.start()
        logger.info(f"Web server started successfully on http://{config.WEB_SERVER_HOST}:{config.WEB_SERVER_PORT}")
        # 서버가 계속 실행되도록 유지 (main.py의 asyncio.gather가 이 역할을 함)
        # 여기서는 시작 후 바로 리턴하여 gather에서 다른 태스크와 함께 관리되도록 함
    except OSError as e:
        # 포트 사용 중 오류 등 처리
        logger.critical(f"Failed to start web server on port {config.WEB_SERVER_PORT}: {e}")
        # 필요시 프로그램 종료 또는 재시도 로직
        await runner.cleanup() # 시작 실패 시 리소스 정리
        raise # 오류를 다시 발생시켜 main에서 처리하도록 함
    except Exception as e:
        logger.critical(f"An unexpected error occurred while starting the web server: {e}", exc_info=True)
        await runner.cleanup()
        raise

    # 웹 서버 종료 시 리소스 정리 (AppRunner cleanup)
    # 일반적으로 main.py의 종료 처리 부분에서 runner.cleanup()을 호출하는 것이 더 적합
    # 여기에 추가한다면:
    # try:
    #     # 앱이 종료될 때까지 대기하는 로직이 필요할 수 있음
    #     # 예: asyncio.Event 사용
    # finally:
    #     await runner.cleanup()
    #     logger.info("Web server runner cleaned up.")

    # start_web_server는 서버를 시작만 하고, 실제 종료 대기는 main.py의 gather에서 처리
    return runner # runner 객체를 반환하여 main 등에서 cleanup 호출 가능하게 함
