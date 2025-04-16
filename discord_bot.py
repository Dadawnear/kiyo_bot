import os
import discord
import asyncio
import re
from datetime import datetime, timezone
import logging
from dotenv import load_dotenv
from kiyo_brain import generate_kiyo_message, generate_kiyo_memory_summary, generate_diary_and_image
from notion_utils import (
    generate_diary_entry,
    upload_to_notion,
    detect_emotion,
    generate_observation_log,
    upload_observation_to_notion,
    upload_memory_to_notion,
    get_last_diary_timestamp
)

load_dotenv()
logging.basicConfig(level=logging.DEBUG)

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
USER_DISCORD_NAME = os.getenv("USER_DISCORD_NAME")
MIDJOURNEY_CHANNEL_NAME = "midjourney-image-channel"

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True
intents.dm_messages = True

client = discord.Client(intents=intents)
conversation_log = []
latest_midjourney_image_url = None

def is_target_user(message):
    return str(message.author) == USER_DISCORD_NAME

def extract_image_url(text):
    match = re.search(r"(https://cdn\.discordapp\.com/attachments/[^\s]+\.(?:png|jpg|jpeg))", text)
    return match.group(1) if match else None

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
    global latest_midjourney_image_url

    logging.debug(f"[on_message] 받은 메시지: {message.content} from {message.author}")

    if message.author == client.user:
        return

    if (
        isinstance(message.channel, discord.TextChannel) and
        message.channel.name == MIDJOURNEY_CHANNEL_NAME and 
        message.author.bot
    ):
        url = extract_image_url(message.content)
        if url:
            latest_midjourney_image_url = url
            logging.info(f"[MJ] Midjourney 이미지 URL 저장됨: {url}")
        return

    if not is_target_user(message):
        return

    if isinstance(message.channel, discord.DMChannel) and message.content.startswith("!cleanup"):
        match = re.search(r"!cleanup(\d*)", message.content.strip())
        limit = int(match.group(1)) if match and match.group(1).isdigit() else 1
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
            match = re.search(r"!diary\s+(\w+)", message.content)
            style = match.group(1) if match else "full_diary"

            last_diary_time = get_last_diary_timestamp()
            if last_diary_time and last_diary_time.tzinfo is None:
                last_diary_time = last_diary_time.replace(tzinfo=timezone.utc)

            filtered_log = [(speaker, text) for speaker, text in conversation_log]

            diary_text, _ = await generate_diary_and_image(
                filtered_log, client, style=style, latest_image_url=latest_midjourney_image_url
            )

            if diary_text:
                emotion = await detect_emotion(diary_text)
                await upload_to_notion(diary_text, emotion_key=emotion, image_url=latest_midjourney_image_url)
                await message.channel.send(f"스타일: `{style}` | 감정: `{emotion}` — 일기와 사진을 남겼어. 크크…")
                latest_midjourney_image_url = None
            else:
                await message.channel.send("크크… 일기 작성이 지금은 어려운 것 같아.")
        except Exception as e:
            logging.error(f"[ERROR] 일기 생성 중 오류: {repr(e)}")
            await message.channel.send("크크… 일기 작성이 지금은 어려운 것 같아. 조금 있다가 다시 시도해줘.")
        return

    if message.content.strip().startswith("!observe"):
        try:
            observation_text = await generate_observation_log(conversation_log)
            await upload_observation_to_notion(observation_text)
            await message.channel.send("크크… 오늘의 서영 관찰 기록도 정리해뒀어.")
        except Exception as e:
            logging.error(f"[ERROR] 관찰 기록 생성 오류: {repr(e)}")
            await message.channel.send("크크… 관찰 일지를 지금은 쓸 수 없네.")
        return

    if any(keyword in message.content for keyword in ["기억해", "기억해줘", "잊지 마", "기억할래", "기억 좀"]):
        try:
            summary = await generate_kiyo_memory_summary(message.content)
            await upload_memory_to_notion(
                original_text=message.content,
                summary=summary,
                tags=[],
                category="감정",
                message_url=message.jump_url
            )
            await message.channel.send("크크… 네 말, 기억해둘게.")
        except Exception as e:
            logging.error(f"[ERROR] 기억 저장 중 오류: {repr(e)}")

    if not message.content.strip():
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
