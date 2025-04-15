import os
import discord
import asyncio
from dotenv import load_dotenv
from kiyo_brain import (
    generate_kiyo_message,
    generate_diary_and_image,
    detect_emotion
)
from notion_utils import upload_to_notion, fetch_recent_notion_summary
import logging

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
USER_DISCORD_NAME = os.getenv("USER_DISCORD_NAME")

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
intents.dm_messages = True

client = discord.Client(intents=intents)
conversation_log = []

logging.basicConfig(level=logging.DEBUG)

def is_target_user(message):
    return str(message.author) == USER_DISCORD_NAME

@client.event
async def on_ready():
    print(f"[READY] Logged in as {client.user}")
    try:
        from scheduler import setup_scheduler
        setup_scheduler(client, conversation_log)
    except Exception as e:
        logging.error(f"[ERROR] 스케줄러 설정 중 오류: {repr(e)}")

@client.event
async def on_message(message):
    logging.debug(f"[DEBUG] author: {message.author}, content: {message.content}")

    if message.author == client.user:
        return

    if not is_target_user(message):
        return

    if isinstance(message.channel, discord.DMChannel) and message.content.startswith("!cleanup"):
        parts = message.content.strip().split()
        limit = 10
        if len(parts) == 2 and parts[1].isdigit():
            limit = int(parts[1])
        await message.channel.send(f"{limit}개의 메시지를 정리할게. 크크…")
        deleted = 0
        async for msg in message.channel.history(limit=limit + 20):
            if msg.author == client.user:
                await msg.delete()
                deleted += 1
                if deleted >= limit:
                    break
        conversation_log.clear()
        return

    if message.content.strip().startswith("!diary"):
        if not conversation_log:
            await message.channel.send("크크… 아직 나눈 이야기가 없네.")
            return
        last_user_msg = conversation_log[-2][1] if len(conversation_log) >= 2 else message.content
        last_kiyo_response = conversation_log[-1][1] if conversation_log[-1][0] == "キヨ" else ""
        emotion = await detect_emotion(last_user_msg)
        await upload_to_notion(last_kiyo_response, emotion=emotion)
        await message.channel.send("방금 대화를 일기로 남겼어. 크크…")
        return

    if not message.content.strip():
        return

    conversation_log.append(("정서영", message.content))

    try:
        response = await generate_kiyo_message(conversation_log)
        conversation_log.append(("キヨ", response))
        await message.channel.send(response)
    except Exception as e:
        logging.error(f"[ERROR] 응답 생성 중 오류 발생: {repr(e)}")
        await message.channel.send("크크… 내가 지금은 응답을 만들 수 없어. 하지만 함수엔 잘 들어왔어.")

async def start_discord_bot():
    await client.start(DISCORD_BOT_TOKEN)
