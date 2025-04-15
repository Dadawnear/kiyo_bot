import os
import requests
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = "1d63ecdaf4c380968badd1d25ab21ca5"  # 갤러리 DB ID

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

async def upload_diary_entry_with_image(text, image_url, tags=[]):
    today = datetime.now()
    date_str = today.strftime("%Y년 %m월 %d일 일기")
    iso_date = today.strftime("%Y-%m-%d")

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
                "type": "image",
                "image": {
                    "type": "external",
                    "external": { "url": image_url }
                }
            },
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
    if response.status_code != 200:
        print("❌ Failed to create diary entry:", response.status_code, response.text)
    else:
        print("✅ Diary entry created successfully.")

async def fetch_recent_notion_summary():
    url = "https://api.notion.com/v1/databases/{}/query".format(NOTION_DATABASE_ID)
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
        print("Failed to fetch Notion content:", response.text)
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

# 일반 텍스트만 추가할 경우에도 쓸 수 있는 버전
async def upload_to_notion(text):
    await upload_diary_entry_with_image(text, image_url="https://via.placeholder.com/1", tags=[])
