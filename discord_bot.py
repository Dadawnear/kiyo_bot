import os
import discord
import asyncio
from dotenv import load_dotenv
from kiyo_brain import (
    generate_kiyo_message,
    generate_diary_entry,
    detect_emotion
)
from notion_utils import upload_to_notion, fetch_recent_notion_summary, get_last_diary_timestamp
import logging
from datetime import datetime, timedelta
import re

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
    logging.debug(f"[on_message] 받은 메시지: {message.content} from {message.author}")

    if message.author == client.user:
        logging.debug("[on_message] 봇 자신의 메시지라 무시")
        return

    if not is_target_user(message):
        logging.debug("[on_message] 타겟 유저가 아님")
        return

    if isinstance(message.channel, discord.DMChannel) and message.content.startswith("!cleanup"):
        match = re.search(r"!cleanup(\d*)", message.content.strip())
        limit = int(match.group(1)) if match and match.group(1).isdigit() else 2
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

        try:
            last_diary_time = await get_last_diary_timestamp()
            filtered_log = [entry for entry in conversation_log if entry[0] != "キヨ" or getattr(entry, 'timestamp', datetime.now()) > last_diary_time]
            diary_text = await generate_diary_entry(filtered_log)
            emotion = await detect_emotion(diary_text)
            await upload_to_notion(diary_text, emotion)
            await message.channel.send("방금까지의 대화를 일기로 남겼어. 크크…")
        except Exception as e:
            logging.error(f"[ERROR] 일기 생성 중 오류: {repr(e)}")
            await message.channel.send("크크… 일기 작성이 지금은 어려운 것 같아. 조금 있다가 다시 시도해줘.")
        return

    if not message.content.strip():
        logging.debug("[on_message] 빈 메시지라 무시")
        return

    conversation_log.append(("정서영", message.content))

    try:
        logging.debug("[GPT] generate_kiyo_message 시작")
        start = datetime.now()
        response = await generate_kiyo_message(conversation_log)
        elapsed = (datetime.now() - start).total_seconds()
        logging.debug(f"[GPT] 응답 완료, 소요 시간: {elapsed:.2f}초")

        conversation_log.append(("キヨ", response))
        await message.channel.send(response)
    except Exception as e:
        logging.error(f"[ERROR] 응답 생성 중 오류 발생: {repr(e)}")
        await message.channel.send("크크… 내가 지금은 응답을 만들 수 없어. 하지만 함수엔 잘 들어왔어.")

async def start_discord_bot():
    await client.start(DISCORD_BOT_TOKEN)
