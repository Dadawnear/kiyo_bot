import os
import discord
import asyncio
from dotenv import load_dotenv
from kiyo_brain import (
    generate_kiyo_message,
    generate_diary_and_image
)
from notion_utils import upload_to_notion, fetch_recent_notion_summary
from scheduler import setup_scheduler

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
USER_DISCORD_NAME = os.getenv("USER_DISCORD_NAME")

client = discord.Client(intents=discord.Intents.all())
conversation_log = []

def is_target_user(message):
    return str(message.author) == USER_DISCORD_NAME

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    setup_scheduler()

@client.event
async def on_message(message):
    if message.author == client.user or not is_target_user(message):
        return

    # ✅ DM에서 !cleanup 명령 처리
    if isinstance(message.channel, discord.DMChannel) and message.content.startswith("!cleanup"):
        parts = message.content.strip().split()
        limit = 10  # 기본 삭제 개수
        if len(parts) == 2 and parts[1].isdigit():
            limit = int(parts[1])
        await message.channel.send(f"{limit}개의 메시지를 정리할게. 크크…")
        deleted = 0
        async for msg in message.channel.history(limit=limit + 20):  # 여유 있게 탐색
            if msg.author == client.user:
                await msg.delete()
                deleted += 1
                if deleted >= limit:
                    break
        conversation_log.clear()
        return

    # ✅ 일반 메시지 처리
    if not message.content.strip():
        return

    if len(conversation_log) == 0:
        conversation_log.append(("정서영", message.content))
    else:
        conversation_log.append(("정서영", message.content))

    try:
        print("[DEBUG] 사용자 입력 메시지:", message.content)
        response = await generate_kiyo_message(conversation_log)
        print("[DEBUG] 생성된 응답:", response)
        conversation_log.append(("キヨ", response))
        await message.channel.send(response)
    except Exception as e:
        print("[ERROR] 응답 생성 중 오류:", e)
        await message.channel.send("크크… 뭔가 문제가 있었던 것 같아. 다시 말해줄래?")

async def send_daily_summary():
    if conversation_log:
        await generate_diary_and_image(conversation_log)
        conversation_log.clear()

async def start_discord_bot():
    await client.start(DISCORD_BOT_TOKEN)
