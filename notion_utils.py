import os
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta
import logging
from openai import AsyncOpenAI

load_dotenv()
logging.getLogger().setLevel(logging.DEBUG)

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# 감정 태그 매핑 (이중 감정 표현 포함)
EMOTION_TAGS = {
    "자신감": ["고요", "자부심"],
    "불안": ["혼란", "불확실성"],
    "애정_서영": ["연애", "애정", "의존"],
    "불만_서영": ["질투", "분노", "소외감"],
    "망상": ["집착", "환각", "해석"],
    "기록": ["중립", "관찰"]
}

def get_virtual_diary_date():
    return datetime.now()

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

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_dialogue}
    ]

    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.7
    )
    logging.debug("[DIARY] 일기 생성 완료")
    return response.choices[0].message.content.strip()

async def upload_diary_entry(text, emotion_key="기록"):
    diary_date = get_virtual_diary_date()
    date_str = diary_date.strftime("%Y년 %m월 %d일 일기")
    iso_date = diary_date.strftime("%Y-%m-%d")
    tags = EMOTION_TAGS.get(emotion_key, ["중립"])

    time_info = diary_date.strftime("%p %I:%M").replace("AM", "오전").replace("PM", "오후")
    meta_block = {
        "object": "block",
        "type": "quote",
        "quote": {
            "rich_text": [
                {"type": "text", "text": {"content": f"🕰️ 작성 시간: {time_info}"}}
            ]
        }
    }

    url = "https://api.notion.com/v1/pages"
    data = {
        "parent": { "database_id": NOTION_DATABASE_ID },
        "properties": {
            "Name": {
                "title": [{"text": {"content": date_str}}]
            },
            "날짜": {
                "date": { "start": iso_date }
            },
            "태그": {
                "multi_select": [{"name": tag} for tag in tags]
            }
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
    try:
        result = response.json()
    except Exception:
        result = {}

    if response.status_code != 200:
        logging.error(f"[NOTION ERROR] {response.status_code} - {result}")
    else:
        logging.info(f"[NOTION] 일기 생성 성공: {result.get('id', '응답에 ID 없음')}")
