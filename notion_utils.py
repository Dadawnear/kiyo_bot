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

async def upload_to_notion(text, emotion="중립"):
    logging.debug(f"[NOTION DEBUG] upload_to_notion 호출됨, emotion: {emotion}")
    try:
        await upload_diary_entry(text, emotion=emotion)
        logging.debug("[NOTION DEBUG] upload_diary_entry 호출 완료")
    except Exception as e:
        logging.error(f"[NOTION ERROR] upload_to_notion 내부 오류: {e}")
