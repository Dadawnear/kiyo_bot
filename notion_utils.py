import os
import discord
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import logging
import re
import requests
from openai import AsyncOpenAI

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
USER_DISCORD_NAME = os.getenv("USER_DISCORD_NAME")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_OBSERVATION_DB_ID = os.getenv("NOTION_OBSERVATION_DB_ID")  # 새 항목
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True
intents.dm_messages = True

client = discord.Client(intents=intents)
conversation_log = []

logging.basicConfig(level=logging.DEBUG)

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

EMOTION_TAGS = {
    "자신감": ["고요", "자부심"],
    "불안": ["혼란", "불확실성"],
    "애정_서영": ["연애", "애정", "의존"],
    "불만_서영": ["질투", "분노", "소외감"],
    "망상": ["집착", "환각", "해석"],
    "기록": ["중립", "관찰"]
}

def is_target_user(message):
    return str(message.author) == USER_DISCORD_NAME

def get_virtual_diary_date():
    return datetime.now()

async def detect_emotion(text):
    if any(kw in text for kw in ["외롭", "쓸쓸", "우울"]):
        return "불안"
    elif any(kw in text for kw in ["사랑", "보고싶", "서영"]):
        return "애정_서영"
    elif any(kw in text for kw in ["짜증", "미워", "질투"]):
        return "불만_서영"
    elif any(kw in text for kw in ["무기력", "비관"]):
        return "망상"
    return "기록"

async def generate_observation_log(conversation_log):
    logging.debug("[OBSERVATION] generate_observation_log 시작")

    # 하루 기준: 오늘 날짜만 필터링
    now = datetime.now(timezone.utc)
    start_of_day = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    today_logs = [
        f"{speaker}: {content}" for speaker, content in conversation_log
        if isinstance(content, str) and len(content.strip()) > 0  # 대사 유효성 검증
    ]

    text = "\n".join(today_logs)
".join(today_logs)
    prompt = (
        "너는 민속학자 신구지 코레키요다. 하루 동안 관찰한 '정서영'이라는 소녀의 특징, 감정 반응, 언어 사용, 관계 맥락 등을 종합해 "
        "관찰 기록을 남긴다. 이 기록은 민속학적 분석을 포함하며, 단순 묘사를 넘어서 인간으로서의 서영에 대한 통찰을 포함해야 한다. "
        "문장은 차분하고 분석적이어야 하며, 마치 학술 노트처럼 읽힌다."
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": text}
    ]

    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

async def upload_observation_to_notion(text):
    now = get_virtual_diary_date()
    date_str = now.strftime("%Y년 %m월 %d일")
    iso_date = now.strftime("%Y-%m-%d")

    payload = {
        "parent": {"database_id": NOTION_OBSERVATION_DB_ID},
        "properties": {
            "이름": {"title": [{"text": {"content": date_str}}]},
            "날짜": {"date": {"start": iso_date}}
        },
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                }
            }
        ]
    }

    try:
        response = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json=payload)
        result = response.json() if response.status_code == 200 else {}
        if response.status_code != 200:
            logging.error(f"[NOTION OBS ERROR] {response.status_code} - {result}")
        else:
            logging.info(f"[NOTION OBS] 업로드 성공: {result.get('id')}")
    except Exception as e:
        logging.error(f"[NOTION OBS ERROR] 업로드 실패: {e}")

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# 수동 트리거용 명령어 추가 예정 / scheduler에도 연결 가능하게 확장 필요

def setup_scheduler(client, conversation_log):

    from kiyo_brain import generate_kiyo_message_with_time
    from notion_utils import generate_diary_entry, detect_emotion, upload_to_notion, generate_observation_log, upload_observation_to_notion

    async def send_kiyo_message(time_context):
        try:
            logging.debug(f"[SCHEDULER] {time_context} 시각 자동 메시지 전송 시작")
            if conversation_log is not None:
                conversation_log.append(("정서영", f"[{time_context}] 시각에 자동 전송된 시스템 메시지"))
                response = await generate_kiyo_message_with_time(conversation_log, time_context)
                conversation_log.append(("キヨ", response))
                user = discord.utils.get(client.users, name=os.getenv("USER_DISCORD_NAME"))
                if user:
                    await user.send(response)
                logging.debug("[SCHEDULER] 키요 메시지 전송 완료")
        except Exception as e:
            logging.error(f"[ERROR] scheduled message error: {repr(e)}")

    async def send_daily_summary():
        try:
            logging.debug("[SCHEDULER] 일기 자동 생성 시작")
            if conversation_log:
                import random
                styles = ["full_diary", "dream_record", "fragment", "ritual_entry"]
                chosen_style = random.choice(styles)
                logging.debug(f"[SCHEDULER] 선택된 일기 스타일: {chosen_style}")

                diary_text = await generate_diary_entry(conversation_log, style=chosen_style)
                emotion = await detect_emotion(diary_text)
                await upload_to_notion(diary_text, emotion_key=emotion)
                logging.info("[SCHEDULER] 자동 일기 업로드 완료")
        except Exception as e:
            logging.error(f"[ERROR] 일기 업로드 중 오류: {repr(e)}")

    async def send_daily_observation():
        try:
            logging.debug("[SCHEDULER] 서영 관찰 기록 자동 생성 시작")
            observation_text = await generate_observation_log(conversation_log)
            await upload_observation_to_notion(observation_text)
            logging.info("[SCHEDULER] 관찰 기록 업로드 완료")
        except Exception as e:
            logging.error(f"[ERROR] 관찰 기록 업로드 중 오류: {repr(e)}")

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(lambda: asyncio.create_task(send_kiyo_message("morning")), CronTrigger(hour=9, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_kiyo_message("lunch")), CronTrigger(hour=12, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_kiyo_message("evening")), CronTrigger(hour=18, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_kiyo_message("night")), CronTrigger(hour=23, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_daily_summary()), CronTrigger(hour=2, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_daily_observation()), CronTrigger(hour=2, minute=5))

    scheduler.start()
