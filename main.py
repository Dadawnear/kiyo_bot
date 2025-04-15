import asyncio
import os
from discord_bot import start_discord_bot
from aiohttp import web

os.environ["TZ"] = "Asia/Seoul"

# 간단한 HTTP 서버 (Render 포트용)
async def handle(request):
    return web.Response(text="Discord bot is running.")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)

    port = int(os.environ.get("PORT", 10000))  # Render는 PORT 환경변수로 포트를 제공해
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server running on port {port}")

# 메인 실행
async def main():
    # 디스코드 봇과 웹서버를 동시에 실행
    await asyncio.gather(
        start_discord_bot(),
        start_web_server()
    )

if __name__ == '__main__':
    asyncio.run(main())
