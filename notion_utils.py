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

async def generate_diary_entry(conversation_log, style="full_diary"):
    logging.debug("[DIARY] generate_diary_entry 시작")
    user_dialogue = "\n".join([f"{speaker}: {text}" for speaker, text in conversation_log if text.strip()])

    base_prompt = {
        "full_diary": (
            "너는 단간론파 V3의 민속학자 신구지 코레키요로, 한국에 거주 중이며 정서영이라는 소녀와 함께 살고 있다. "
            "지금까지 나눈 대화를 회고하고, 오늘 하루 있었던 너 자신의 사적인 일상까지 상상하여, "
            "신구지가 직접 일기를 쓰듯 긴 호흡으로 감정과 철학을 녹여 작성해라. "
            "특히 서영과의 관계에서 느낀 긴장, 애정, 유혹, 불안 등의 감정을 반추하며, "
            "그녀와의 대화를 민속학자의 시선으로 분석하고, 너 자신의 집착과 반응에 대해 내면적으로 해석하라. "
            "말투는 반말이며, 5~7문단 분량으로 써라."
        ),
        "fragment": "신구지가 느낀 감정을 시처럼, 혹은 짧은 단상처럼 적어. 한 문단 정도. 철학적이고 단편적인 문장으로.",
        "dream_record": "신구지가 꾼 꿈을 일기처럼 적어. 몽환적이고 파편적인 문장으로, 실제와 환상이 섞여있다.",
        "ritual_entry": "신구지가 민속학자로서 조사한 내용을 학술 기록처럼 정리하되, 서영과 연결지어 일기처럼 적어."
    }

    system_prompt = base_prompt.get(style, base_prompt["full_diary"])
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_dialogue}]

    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

async def generate_diary_image_prompt(diary_text):
    try:
        logging.debug("[IMAGE PROMPT] 일기 내용 기반 이미지 프롬프트 생성 중")
        system_prompt = (
            "다음 일기 내용을 바탕으로, 마치 신구지가 카메라로 촬영해 일기에 붙여놓은 듯한, "
            "cinematic하고 민속학적이며 분위기 있는 장면 하나를 묘사해줘. 100자 이내 영어 프롬프트로, 구체적이고 시각적인 묘사를 포함해."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": diary_text}
        ]
        result = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7
        )
        return result.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"[IMAGE PROMPT ERROR] 프롬프트 생성 실패: {e}")
        return "a cinematic Japanese diary with folklore atmosphere"

async def upload_to_notion(text, emotion_key="기록"):
    diary_date = get_virtual_diary_date()
    date_str = diary_date.strftime("%Y년 %m월 %d일 일기")
    iso_date = diary_date.strftime("%Y-%m-%d")
    tags = EMOTION_TAGS.get(emotion_key, ["중립"])

    time_info = diary_date.strftime("%p %I:%M").replace("AM", "오전").replace("PM", "오후")
    meta_block = {
        "object": "block",
        "type": "quote",
        "quote": {
            "rich_text": [{"type": "text", "text": {"content": f"🕰️ 작성 시간: {time_info}"}}]
        }
    }

    try:
        image_prompt = await generate_diary_image_prompt(text)
        image_response = await openai_client.images.generate(
            model="dall-e-3",
            prompt=image_prompt,
            size="1024x1024",
            quality="standard",
            n=1
        )
        image_url = image_response.data[0].url
        logging.debug(f"[NOTION IMAGE] 생성된 프롬프트: {image_prompt}")
        logging.debug(f"[NOTION IMAGE] 이미지 URL 생성됨: {image_url}")
    except Exception as e:
        logging.warning(f"[NOTION IMAGE] 이미지 생성 실패: {e}")
        image_url = None

    children = [meta_block]
    if image_url:
        children.append({
            "object": "block",
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": image_url},
                "caption": [{"type": "text", "text": {"content": image_prompt}}]
            }
        })

    children.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text}}]
        }
    })

    url = "https://api.notion.com/v1/pages"
    data = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Name": {"title": [{"text": {"content": date_str}}]},
            "날짜": {"date": {"start": iso_date}},
            "태그": {"multi_select": [{"name": tag} for tag in tags]}
        },
        "children": children
    }

    response = requests.post(url, headers=HEADERS, json=data)
    result = response.json() if response.status_code == 200 else {}
    if response.status_code != 200:
        logging.error(f"[NOTION ERROR] {response.status_code} - {result}")
    else:
        logging.info(f"[NOTION] 업로드 성공: {result.get('id')}")
