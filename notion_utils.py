import os
import requests
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_PAGE_ID = os.getenv("NOTION_PAGE_ID")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

NOTION_BLOCK_URL = f"https://api.notion.com/v1/blocks/{NOTION_PAGE_ID}/children"

async def upload_to_notion(text):
    data = {
        "children": [{
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {
                        "content": text
                    }
                }]
            }
        }]
    }
    response = requests.patch(NOTION_BLOCK_URL, headers=HEADERS, json=data)
    if response.status_code != 200:
        print("Failed to upload to Notion:", response.text)

async def upload_diary_entry_with_image(text, image_url):
    date_str = datetime.now().strftime("%Y년 %m월 %d일 일기")
    data = {
        "children": [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": date_str}}]
                }
            },
            {
                "object": "block",
                "type": "image",
                "image": {
                    "type": "external",
                    "external": {"url": image_url}
                }
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                }
            }
        ]
    }
    response = requests.patch(NOTION_BLOCK_URL, headers=HEADERS, json=data)
    if response.status_code != 200:
        print("Failed to upload diary entry with image:", response.text)

async def fetch_recent_notion_summary():
    read_url = f"https://api.notion.com/v1/blocks/{NOTION_PAGE_ID}/children?page_size=5"
    response = requests.get(read_url, headers=HEADERS)
    if response.status_code != 200:
        print("Failed to fetch Notion content:", response.text)
        return "최근 일기를 불러올 수 없습니다."

    data = response.json()
    texts = []
    for block in data.get("results", []):
        if block["type"] == "paragraph":
            rich_text = block["paragraph"].get("rich_text", [])
            for rt in rich_text:
                if rt["type"] == "text":
                    texts.append(rt["text"]["content"])

    summary = "\n".join(texts[-3:])
    return summary if summary else "최근 일기가 존재하지 않습니다."
