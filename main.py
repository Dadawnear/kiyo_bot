import asyncio
import os
from discord_bot import start_discord_bot, get_last_user_message_time
from initiate_checker import check_initiate_message
from aiohttp import web

os.environ["TZ"] = "Asia/Seoul"

# 루트 핸들러
async def handle_root(request):
    return web.Response(text="Discord bot is running.")

# 헬스 체크 핸들러
async def handle_health(request):
    return web.Response(text="OK")

# 웹 서버 시작
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/health", handle_health)

    port = int(os.environ.get("PORT", 10000))  # Render에서 제공하는 포트 사용
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server running on port {port}")

# 선톡 루프 설정
async def loop_initiate_checker():
    await bot.wait_until_ready()
    await check_initiate_message(bot, USER_ID, get_last_user_message_time)

# 메인 실행
async def main():
    # 디스코드 봇과 웹서버를 동시에 실행
    await asyncio.gather(
        start_discord_bot(),
        start_web_server()
    )

if __name__ == '__main__':
    asyncio.run(main())
