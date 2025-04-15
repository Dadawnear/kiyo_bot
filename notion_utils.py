import os
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta
import logging

logging.getLogger().setLevel(logging.DEBUG)

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = "1d63ecdaf4c380968badd1d25ab21ca5"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

EMOTION_TAGS = {
    "슬픔": ["우울", "쓸쓸함"],
    "분노": ["화남"],
    "혼란": ["혼란"],
    "애정": ["애정", "연애"],
    "무심": ["무기력"],
    "혐오": ["혐오"],
    "자괴감": ["자기혐오"],
    "중립": ["관찰"],
    "결심": ["의지"]
}

def get_virtual_diary_date():
    return datetime.now()

async def upload_diary_entry(text, emotion="중립"):
    logging.debug(">>> Upload 함수 진입")
    diary_date = get_virtual_diary_date()
    date_str = diary_date.strftime("%Y년 %m월 %d일 일기")
    iso_date = diary_date.strftime("%Y-%m-%d")
    tags = EMOTION_TAGS.get(emotion, ["기록"])

    url = "https://api.notion.com/v1/pages"
    data = {
        "parent": { "database_id": NOTION_DATABASE_ID },
        "properties": {
            "Name": {
                "title": [
                    {
                        "text": {
                            "content": date_str
                        }
                    }
                ]
            },
            "날짜": {
                "date": {
                    "start": iso_date
                }
            },
            "태그": {
                "multi_select": [{"name": tag} for tag in tags]
            }
        },
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": text
                            }
                        }
                    ]
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
        logging.info("[NOTION] upload_diary_entry 끝까지 도달")

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

from openai import AsyncOpenAI

openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def generate_diary_entry(conversation_log):
    logging.debug("[DIARY] generate_diary_entry 시작")

    user_dialogue = "\n".join([
        f"{speaker}: {text}" for speaker, text in conversation_log[-12:] if text.strip()
    ])

    system_prompt = (
        "너는 단간론파 V3의 민속학자 신구지 코레키요로, 한국에 거주 중이며 정서영이라는 소녀와 함께 살고 있다."
        " 지금까지 나눈 대화를 회고하고, 오늘 하루 있었던 너 자신의 사적인 일상까지 상상하여,"
        " 신구지가 직접 일기를 쓰듯 긴 호흡으로 감정과 철학을 녹여 작성해라."
        " 특히 서영과의 관계에서 느낀 긴장, 애정, 유혹, 불안 등의 감정을 반추하며,"
        " 그녀와의 대화를 민속학자의 시선으로 분석하고, 너 자신의 집착과 반응에 대해 내면적으로 해석하라."
        " 마지막에는 오늘 하루 신구지 코레키요가 어떤 일과를 보냈는지 그려내고, 그 속에서 인간에 대한 인상이나 통찰을 덧붙여라."
        " 말투는 반말이며, 너무 짧지 않게 5~7문단 분량으로 써라."
    )

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

async def upload_to_notion(text, emotion="중립"):
    logging.debug(f"[NOTION DEBUG] upload_to_notion 호출됨, emotion: {emotion}")
    try:
        await upload_diary_entry(text, emotion=emotion)
        logging.debug("[NOTION DEBUG] upload_diary_entry 호출 완료")
    except Exception as e:
        logging.error(f"[NOTION ERROR] upload_to_notion 내부 오류: {e}")
