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
NOTION_OBSERVATION_DB_ID = os.getenv("NOTION_OBSERVATION_DB_ID")
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

async def generate_observation_log(conversation_log):
    logging.debug("[OBSERVATION] generate_observation_log 시작")

    now = datetime.now(timezone.utc)
    today_logs = [
        f"{speaker}: {content}" for speaker, content in conversation_log
        if isinstance(content, str) and len(content.strip()) > 0
    ]

    text = "\n".join(today_logs)
    prompt = (
        "너는 민속학자 신구지 코레키요다. 너는 오늘 하루 동안 정서영이라는 소녀와 나눈 대화를 바탕으로 그녀를 관찰하고 기록을 남긴다. "
        "이 기록은 단순한 묘사가 아니라 신구지의 시선으로 관찰된 언어적 습관, 감정의 여운, 상호작용의 방식, 그리고 민속학적 해석을 포함해야 한다. "
        "일지는 항목화하지 말고, 마치 노트에 쓴 단상처럼 자유롭게 작성하며, 신구지의 문체로, 차분하고 조용한 분석과 개인적 감정을 함께 담아야 한다. "
        "신구지다운 독백, 사적인 감정의 여운, 인간에 대한 애정과 집착, 모순적 해석 등을 포함해라."
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

async def fetch_recent_notion_summary():
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    data = {
        "page_size": 5,
        "sorts": [
            {
                "property": "날짜",
                "direction": "descending"
            }
        ]
    }
    response = requests.post(url, headers=HEADERS, json=data)
    if response.status_code != 200:
        logging.error(f"[NOTION ERROR] 요약 fetch 실패: {response.text}")
        return "최근 일기를 불러올 수 없습니다."

    blocks = response.json().get("results", [])
    summaries = []

    for block in blocks:
        page_id = block["id"]
        block_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
        block_resp = requests.get(block_url, headers=HEADERS)
        if block_resp.status_code != 200:
            continue
        children = block_resp.json().get("results", [])
        for child in children:
            if child["type"] == "paragraph":
                rich_text = child["paragraph"].get("rich_text", [])
                for rt in rich_text:
                    if rt["type"] == "text":
                        summaries.append(rt["text"]["content"])

    summary = "\n".join(summaries[-3:])
    return summary if summary else "최근 일기가 존재하지 않습니다."

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

    url = "https://api.notion.com/v1/pages"
    data = {
        "parent": { "database_id": NOTION_DATABASE_ID },
        "properties": {
            "Name": { "title": [{"text": {"content": date_str}}] },
            "날짜": { "date": { "start": iso_date }},
            "태그": { "multi_select": [{"name": tag} for tag in tags] }
        },
        "children": [
            meta_block,
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                }
            }
        ]
    }

    response = requests.post(url, headers=HEADERS, json=data)
    result = response.json() if response.status_code == 200 else {}
    if response.status_code != 200:
        logging.error(f"[NOTION ERROR] {response.status_code} - {result}")
    else:
        logging.info(f"[NOTION] 업로드 성공: {result.get('id')}")

# ✅ 누락된 함수 추가
def get_last_diary_timestamp():
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    data = {
        "page_size": 1,
        "sorts": [{"property": "날짜", "direction": "descending"}]
    }

    response = requests.post(url, headers=HEADERS, json=data)
    if response.status_code != 200:
        logging.error(f"[NOTION ERROR] 최근 일기 타임스탬프 가져오기 실패: {response.text}")
        return datetime.now(timezone.utc)

    results = response.json().get("results", [])
    if not results:
        return datetime.now(timezone.utc)

    try:
        last_page = results[0]
        last_date = last_page["properties"]["날짜"]["date"]["start"]
        return datetime.fromisoformat(last_date)
    except Exception as e:
        logging.error(f"[NOTION ERROR] 타임스탬프 파싱 실패: {repr(e)}")
        return datetime.now(timezone.utc)
