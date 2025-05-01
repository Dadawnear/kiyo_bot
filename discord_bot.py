
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
    get_last_diary_timestamp,
    update_diary_image,
    get_latest_diary_page_id,
    fetch_pending_todos, 
    mark_reminder_sent
)

load_dotenv()
logging.basicConfig(level=logging.DEBUG)

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
USER_DISCORD_NAME = os.getenv("USER_DISCORD_NAME")
MIDJOURNEY_CHANNEL_NAME = "midjourney-image-channel"
MIDJOURNEY_BOT_ID = os.getenv("MIDJOURNEY_BOT_ID")

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True
intents.dm_messages = True

client = discord.Client(intents=intents)
last_midjourney_message = {}
conversation_log = []
latest_midjourney_image_url = None
last_created_diary_page_id = None
scheduler_initialized = False

def get_latest_image_url():
    return latest_midjourney_image_url

def clear_latest_image_url():
    global latest_midjourney_image_url
    latest_midjourney_image_url = None

def is_target_user(message):
    return str(message.author) == USER_DISCORD_NAME

def extract_image_url_from_message(message):
    for attachment in message.attachments:
        url_without_query = attachment.url.split("?")[0]
        if url_without_query.endswith((".png", ".jpg", ".jpeg")):
            return attachment.url
    for embed in message.embeds:
        if embed.type == "image" and embed.url:
            return embed.url
        if embed.thumbnail and embed.thumbnail.url:
            return embed.thumbnail.url
        if embed.image and embed.image.url:
            return embed.image.url
    return None

def is_upscaled_image(message):
    # Midjourney 업스케일 메시지엔 보통 "Image #1" ~ "Image #4" 같은 표현이 들어감
    return bool(re.search(r"Image\s+#\d", message.content))

async def check_todo_reminders():
    try:
        logging.debug("[REMINDER] 할 일 리마인더 체크 시작")
        todos = fetch_pending_todos()
        user = discord.utils.get(client.users, name=USER_DISCORD_NAME)

        for todo in todos:
            task_name = todo['properties']['할 일']['title'][0]['plain_text']
            page_id = todo['id']
            attempts = todo['properties'].get('리마인드 시도 수', {}).get('number', 0) + 1

            if user:
                await user.send(f"크크… 오늘 네가 해야 할 일 중 하나는 이것이야:\n**{task_name}**\n…벌써 했는지는 모르겠지만, 난 확인하러 왔어.")
                logging.debug(f"[REMINDER] ✅ '{task_name}'에 대한 리마인더 전송 완료")

                mark_reminder_sent(page_id, attempts)
            else:
                logging.warning("[REMINDER] ❗ 대상 유저 찾을 수 없음")

    except Exception as e:
        logging.error(f"[REMINDER ERROR] 리마인더 전송 중 오류 발생: {repr(e)}")

async def reminder_loop():
    while True:
        await check_todo_reminders()
        await asyncio.sleep(3600)
        

@client.event
async def on_ready():
    global scheduler_initialized
    print(f"[READY] Logged in as {client.user}")

    if not scheduler_initialized:
        try:
            from scheduler import setup_scheduler
            setup_scheduler(
                client,
                conversation_log,
                get_latest_image_url,
                clear_latest_image_url
            )
            client.loop.create_task(reminder_loop()) # 할 일 체크 루프 시작
            scheduler_initialized = True
            logging.info("[READY] 스케줄러 정상 초기화 완료")
        except Exception as e:
            logging.exception("[ERROR] 스케줄러 설정 중 치명적인 오류 발생:")
    else:
        logging.info("[READY] 스케줄러 이미 초기화됨")

@client.event
async def on_raw_message_edit(payload):
    data = payload.data
    if "attachments" in data and len(data["attachments"]) > 0:
        image_url = data["attachments"][0]["url"]
        if last_created_diary_page_id:
            await update_diary_image(last_created_diary_page_id, image_url)

@client.event
async def on_raw_message_delete(payload):
    deleted_message_id = payload.message_id
    if deleted_message_id in last_midjourney_message:
        image_url = last_midjourney_message[deleted_message_id]
        await update_diary_image(last_created_diary_page_id, image_url)

@client.event
async def on_message(message):
    global latest_midjourney_image_url
    global last_created_diary_page_id

    logging.debug(f"[on_message] 받은 메시지: {message.content} from {message.author}")

    MIDJOURNEY_BOT_ID = os.getenv("MIDJOURNEY_BOT_ID")

    if int(MIDJOURNEY_BOT_ID) == message.author.id and message.attachments:
        last_midjourney_message[message.id] = message.attachments[0].url

    if (
        isinstance(message.channel, discord.TextChannel) and
        message.channel.name == MIDJOURNEY_CHANNEL_NAME and 
        int(MIDJOURNEY_BOT_ID) == message.author.id
    ):
        if is_upscaled_image(message):
            logging.debug("[MJ] ✅ 업스케일 메시지 감지됨.")
            image_url = extract_image_url_from_message(message)
            if image_url:
                logging.info(f"[MJ] ✅ 업스케일 이미지 저장됨: {image_url}")

                if not last_created_diary_page_id:
                    # 마지막 일기 ID를 동적으로 조회
                    last_created_diary_page_id = get_latest_diary_page_id()
                    logging.info(f"[MJ] 🔄 최근 일기 자동 조회됨: {last_created_diary_page_id}")

                if last_created_diary_page_id:
                    logging.info(f"[MJ] 📘 일기 페이지 ID 있음, 이미지 첨부 시도: {last_created_diary_page_id}")
                    await update_diary_image(last_created_diary_page_id, image_url)
                    clear_latest_image_url()
                else:
                    logging.warning("[MJ] ❌ 최근 일기 ID 찾기 실패. 이미지 첨부 불가.")
            else:
                logging.warning(f"[MJ] ⚠️ 업스케일 메시지 감지됨, but 이미지 URL 없음. msg.id: {message.id}")
        else:
            logging.debug(f"[MJ] ⛔ 업스케일 메시지 아님. msg.id: {message.id}")
        return

    if not is_target_user(message):
        return

    if message.content.strip().startswith("!cleanup"):
        match = re.search(r"!cleanup(\d*)", message.content.strip())
        limit = int(match.group(1)) if match and match.group(1).isdigit() else 1
        deleted = 0
        async for msg in message.channel.history(limit=limit + 20):
            if msg.author == client.user:
                await msg.delete()
                deleted += 1
                if deleted >= limit:
                    break
        # 🔧 최근 limit만 제거
        del conversation_log[-limit:] 
        return


    if message.content.strip().startswith("!diary"):
        if not conversation_log:
            await message.channel.send("크크… 아직 나눈 이야기가 없네.")
            return  # ← 이거 반드시 있어야 해!

        try:
            match = re.search(r"!diary\s+(\w+)", message.content)
            style = match.group(1) if match else "full_diary"

            filtered_log = [(entry[0], entry[1]) for entry in conversation_log if len(entry) >= 2]  # ← 기존엔 entry[:2] 식으로 위험한 언팩 사용
            diary_text, _ = await generate_diary_and_image(filtered_log, client, style=style, latest_image_url=None)

            if diary_text:
                emotion = await detect_emotion(diary_text)
                last_created_diary_page_id = await upload_to_notion(diary_text, emotion_key=emotion, image_url=None)
                await message.channel.send(f"스타일: `{style}` | 감정: `{emotion}` — 일기를 남겼어. 크크…")
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

    conversation_log.append(("정서영", message.content, message.channel.id))

    try:
        logging.debug("[GPT] generate_kiyo_message 시작")
        start = datetime.now()
        response = await generate_kiyo_message(conversation_log, channel_id=message.channel.id)
        elapsed = (datetime.now() - start).total_seconds()
        logging.debug(f"[GPT] 응답 완료, 소요 시간: {elapsed:.2f}초")

        conversation_log.append(("キヨ", response, message.channel.id))
        await message.channel.send(response)
    except Exception as e:
        logging.error(f"[ERROR] 응답 생성 중 오류 발생: {repr(e)}")
        await message.channel.send("크크… 내가 지금은 응답을 만들 수 없어. 하지만 함수엔 잘 들어왔어.")

async def start_discord_bot():
    await client.start(DISCORD_BOT_TOKEN)
