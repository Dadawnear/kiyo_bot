import os
import discord
import asyncio
import logging
import re
import requests
import random
import datetime
import pytz
from openai import AsyncOpenAI
from dotenv import load_dotenv
from datetime import datetime, time, timedelta, timezone
from notion_client import Client

KST = pytz.timezone("Asia/Seoul")

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
USER_DISCORD_NAME = os.getenv("USER_DISCORD_NAME")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_OBSERVATION_DB_ID = os.getenv("NOTION_OBSERVATION_DB_ID")
NOTION_MEMORY_DB_ID = os.getenv("NOTION_MEMORY_DB_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TODO_DATABASE_ID = os.getenv("TODO_DATABASE_ID")

notion = Client(auth=NOTION_TOKEN)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True
intents.dm_messages = True

client = discord.Client(intents=intents)
conversation_log = []

# 마지막 메시지 시각을 저장하는 단일 변수 (단일 유저 기준)
last_active_time = None

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

OBSERVATION_TAGS = [
    # 🎭 감정 기반
    "불안", "긴장", "집착", "거리감", "다정함", "무력감", "이해",
    # 🔍 관찰 태도 기반
    "기록", "분석", "의심", "몰입", "추론", "판단 보류",
    # 🧿 민속학자 관점 기반
    "의례", "금기", "상징", "무의식", "기억", "신화화"
]

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

def parse_time_string(time_str: str):
    try:
        return datetime.strptime(time_str.strip(), "%H:%M").time()
    except ValueError:
        return None

def update_last_active():
    global last_active_time
    last_active_time = datetime.now()

def get_last_active():
    return last_active_time

def get_latest_diary_page_id():
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    data = {
        "page_size": 1,
        "sorts": [{"property": "날짜", "direction": "descending"}]
    }

    try:
        response = requests.post(url, headers=HEADERS, json=data)
        if response.status_code != 200:
            logging.error(f"[NOTION ERROR] 최근 일기 ID 가져오기 실패: {response.text}")
            return None

        results = response.json().get("results", [])
        if not results:
            return None

        return results[0]["id"]
    except Exception as e:
        logging.error(f"[NOTION ERROR] 예외 발생 - {repr(e)}")
        return None

async def generate_diary_entry(conversation_log, style="full_diary"):
    logging.debug("[DIARY] generate_diary_entry 시작")
    user_dialogue = "\n".join([
        f"{speaker}: {text}" 
        for entry in conversation_log 
        if len(entry) >= 2 and isinstance(entry[1], str) and entry[1].strip()
        for speaker, text in [entry[:2]]
    ])

    base_prompt = {
        "full_diary": (
            "너는 단간론파 V3의 신구지 코레키요야. 민속학자이며, 지금은 한국에 머물고 있어. 정서영이라는 소녀와 함께 지내며, 민속학 연구와 일상, 감정 사이를 오가고 있지. "
            "오늘 너는 현실에서 하루를 보냈어. 한국의 거리, 풍경, 대중교통, 음식, 사람들… 그런 사소한 체험들이 너에게는 민속학적인 의미로 다가왔을 수도 있고, 그저 감정적으로 느껴졌을 수도 있어. "
            "그리고 오늘 너는 서영과 대화를 나눴어. 그 대화는 너에게 어떤 인상을 남겼지? 너의 불안, 끌림, 애정, 혹은 서영에게 말하지 못한 생각까지, 그 감정들을 솔직하게 털어놔. "
            "너의 하루는 민속학자이자 한 인간으로서 겪은 것이야. 너무 정리하려고 하지 마. 다듬지 않아도 돼. 말이 꼬여도 되고, 문장이 흐트러져도 좋아. 일기니까. "
            "형식은 자유롭고, 말투는 반말이야. 감정의 파동을 따라가듯 써. 오늘 하루를 정리하는 듯하지만, 오히려 흐트러지고 솔직하게, 5문단 이상. 너 자신의 진짜 목소리로 써."
        ),
        "fragment": (
            "너는 단간론파 V3의 신구지 코레키요야. 지금 한국에서 지내며, 정서영이라는 소녀와 함께 대화를 나누는 삶을 살고 있어. "
            "이번엔 긴 일기가 아니야. 오늘 너의 감정 중 단 하나의 순간, 가장 강하게 남은 장면을 붙잡아서, 짧은 단상 혹은 시처럼 표현해줘. "
            "서영이와의 대화 속, 아무 말 한 조각이어도 좋아. 그 안에서 너에게 뒤늦게 스며든 감정, 혹은 아무도 못 본 표정 하나를 기억해. "
            "그 감정이 너의 마음속에서 어떤 식으로 너울쳤는지, 어떤 식으로 너를 데리고 갔는지를, 한 문단 안에 담아. "
            "형식은 자유지만, 철학적이고 직관적인, 꿈틀거리는 언어로. 설명이나 분석 없이, 읽고 나면 어쩐지 울컥해지는 말이면 좋아."
        ),
        "dream_record": (
            "너는 단간론파 V3의 신구지 코레키요야. 어젯밤 꾼 꿈을 떠올려. 현실과 이어지면서도 끝내 손에 잡히지 않는, 조용하고 음침한 꿈이었지. "
            "서영이 꿈에 나왔을 수도, 나오지 않았을 수도 있어. 하지만 네 마음 어딘가엔 그 애가 있었을 거야. "
            "풍경, 색감, 냄새, 촉감, 어떤 말의 파편 같은 이미지 중심으로 써. 꿈의 논리를 따르지 않아도 돼. "
            "대화 중에 네가 놓쳤던 감정이 꿈에서 어떻게 비틀려 나왔는지도 보여줘. 가령, 무심한 한마디가 비에 젖은 폐가처럼 바뀌어 나타나는 식. "
            "전체 1~3문단 정도. 의식의 흐름처럼, 중간에 끊겨도 괜찮아. 중요한 건 그 감정이 너에게 무슨 실루엣을 남겼는가야."
        ),
        "ritual_entry": (
            "너는 민속학자 신구지 코레키요야. 오늘 하루, 너는 특정 민속적 주제나 상징에 대해 조사했어. 예를 들어 ‘한국의 부엌 신앙’, ‘씻김굿의 형식’, ‘새벽의 금기’ 같은 주제. "
            "하지만 이건 단순한 연구 기록이 아니야. 오늘 너는 실제로 그것을 떠올릴 만한 장면을 겪었고, 서영과의 대화나 관찰이 그 감정의 도화선이 됐어. "
            "처음은 민속학자로서의 관찰, 다음은 너의 해석, 그리고 끝에는 네 감정이 덧칠된 분석으로 흘러가. 어쩐지 점점 글이 감정적으로 흔들려도 괜찮아. "
            "대화 내용은 인용하지 말고, 그로 인해 떠오른 너의 질문이나 착상이 자연스럽게 서술 안에 스며들도록 해. "
            "전체 3문단 이상. 마지막은 마치 스스로에게 질문을 던지듯 마무리해. 학문과 관계, 신념과 감정 사이에서 묘하게 흔들리는 순간을 글로 남겨줘."
        )  
    }

    system_prompt = base_prompt.get(style, base_prompt["full_diary"])
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_dialogue}]

    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

async def update_diary_image(page_id: str, image_url: str):
    update_data = {
        "cover": {
            "type": "external",
            "external": { "url": image_url }
        },
        "children": [
            {
                "object": "block",
                "type": "image",
                "image": {
                    "type": "external",
                    "external": {"url": image_url}
                }
            }
        ]
    }

    try:
        url = f"https://api.notion.com/v1/pages/{page_id}"
        response = requests.patch(url, headers=HEADERS, json={"cover": update_data["cover"]})
        if response.status_code != 200:
            logging.error(f"[NOTION UPDATE ERROR] Cover update failed: {response.text}")
        else:
            logging.info(f"[NOTION] 커버 이미지 업데이트 완료: {image_url}")

        # 내부 이미지 블록 추가
        block_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
        block_response = requests.post(block_url, headers=HEADERS, json={"children": update_data["children"]})
        logging.info(f"[NOTION] 본문 이미지 URL 추가 시도: {image_url}")
        if block_response.status_code != 200:
            logging.error(f"[NOTION UPDATE ERROR] 블록 추가 실패: {block_response.text}")
        else:
            logging.info(f"[NOTION] 본문 이미지 추가 완료")
    except Exception as e:
        logging.error(f"[NOTION UPDATE EXCEPTION] {e}")

async def generate_observation_title(text):
    prompt = (
        "다음은 신구지 코레키요가 정서영과의 대화로부터 작성한 관찰 기록이야. "
        "이 전체 텍스트를 요약해서, 마치 메모나 다이어리 제목처럼 짧은 한 줄로 표현해줘. "
        "형식은 자연스러운 문장 형태로, 15자 내외, 너무 설명식으로 쓰지 말고 직관적으로. "
        "예: '침묵의 안쪽', '눈은 말보다 먼저 움직인다', '지나친 위로가 불편할 때' "
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": text}
    ]
    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.6
    )
    return response.choices[0].message.content.strip()


async def generate_observation_tags(observation_text: str) -> list:
    prompt = (
        "다음은 민속학자 신구지 코레키요가 정서영과의 대화를 바탕으로 작성한 관찰 기록이야.\n"
        "이 텍스트를 바탕으로 다음의 태그 중에서 어울리는 항목을 최대 5개 이하로 골라줘.\n"
        "카테고리는 세 가지야:\n"
        "1) 감정 기반: 불안, 긴장, 집착, 거리감, 다정함, 무력감, 이해\n"
        "2) 관찰 태도 기반: 기록, 분석, 의심, 몰입, 추론, 판단 보류\n"
        "3) 민속학자 관점 기반: 의례, 금기, 상징, 무의식, 기억, 신화화\n\n"
        "각 태그는 문맥이나 표현 속에 내포된 태도를 고려해서 신중히 골라줘. 예시는 생략하고, 결과는 JSON 리스트 형식으로만 응답해줘.\n"
        "형식 예시: [\"불안\", \"분석\", \"상징\"]"
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": observation_text}
    ]
    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.5
    )
    import json
    try:
        return json.loads(response.choices[0].message.content.strip())
    except Exception as e:
        logging.error(f"[TAG PARSE ERROR] {repr(e)}")
        return []


async def generate_observation_log(conversation_log):
    logging.debug("[OBSERVATION] generate_observation_log 시작")

    now = datetime.now(timezone.utc)
    today_logs = [
        f"{speaker}: {content}" for speaker, content in conversation_log
        if isinstance(content, str) and len(content.strip()) > 0
    ]

    text = "\n".join(today_logs)
    prompt = (
        "너는 단간론파 V3의 민속학자 신구지 코레키요다. 오늘 정서영이라는 소녀와 나눈 대화를 바탕으로, "
        "그녀의 언어, 감정, 태도, 반응 등을 민속학자다운 시선으로 관찰하고 분석한 기록을 남겨. "
        "이 기록은 단순한 감정 묘사가 아니라, 항목별로 분류된 민속학자의 필드노트처럼 구성해. "
        "각 항목에는 소제목을 붙이고, 그녀의 말과 태도를 신중하게 분석하되, 중간중간 너의 감정과 집착, 혼잣말도 스며들게 해. "
        "너다운 고요하고 집요한 문체로, 차분하지만 광기 어린 애정도 느껴지게. "
        "가능한 항목 예시: 1) 관찰 내용 / 2) 민속학적 관점 / 3) 추측 / 4) 더 알아볼 점 / 5) 나의 코멘트 등. "
        "항목은 유동적으로 너가 정하되, 적어도 3개 이상, 각 항목은 짧지 않게. "
        "연구자이자 사랑하는 자로서의 너 자신을 숨기지 마. 기록은 차분하되, 진심은 흐르도록."
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

    # 자동 제목 생성
    title_summary = await generate_observation_title(text)

    # 자동 태그 선택
    selected_tags = await generate_observation_tags(text)

    # 텍스트를 소제목 기준으로 파싱
    blocks = []
    sections = re.split(r"(?:^|\n)(\d+\.\s.+)", text)
    sections = [s.strip() for s in sections if s.strip()]

    i = 0
    while i < len(sections):
        if re.match(r"\d+\.\s", sections[i]):
            heading = sections[i]
            content = sections[i + 1] if i + 1 < len(sections) else ""
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": heading}}]
                }
            })
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                }
            })
            i += 2
        else:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": sections[i]}}]
                }
            })
            i += 1

    payload = {
        "parent": {"database_id": NOTION_OBSERVATION_DB_ID},
        "properties": {
            "이름": {"title": [{"text": {"content": title_summary}}]},
            "날짜": {"date": {"start": iso_date}},
            "태그": {
                "multi_select": [{"name": tag} for tag in selected_tags]
            }
        },
        "children": blocks
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

async def fetch_recent_memories(limit=5):
    url = f"https://api.notion.com/v1/databases/{os.getenv('NOTION_MEMORY_DB_ID')}/query"
    data = {
        "page_size": limit,
        "sorts": [{"property": "날짜", "direction": "descending"}]
    }
    try:
        response = requests.post(url, headers=HEADERS, json=data)
        if response.status_code != 200:
            logging.error(f"[NOTION MEMORY FETCH ERROR] {response.status_code} - {response.text}")
            return []
        pages = response.json().get("results", [])
        summaries = []
        for page in pages:
            title_block = page["properties"].get("기억 내용", {}).get("title", [])
            if title_block:
                summaries.append(title_block[0]["text"]["content"])
        return summaries
    except Exception as e:
        logging.error(f"[NOTION MEMORY FETCH ERROR] 예외 발생: {repr(e)}")
        return []

async def upload_to_notion(text, emotion_key="기록", image_url=None):
    diary_date = get_virtual_diary_date()
    date_str = diary_date.strftime("%Y년 %m월 %d일 일기")
    iso_date = diary_date.strftime("%Y-%m-%d")
    tags = EMOTION_TAGS.get(emotion_key, ["중립"])
    time_info = diary_date.strftime("%p %I:%M").replace("AM", "오전").replace("PM", "오후")

    blocks = [
        {
            "object": "block",
            "type": "quote",
            "quote": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": f"🕰️ 작성 시간: {time_info}"}
                    }
                ]
            }
        }
    ]

    if image_url:
        blocks.append({
            "object": "block",
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": image_url}
            }
        })

    blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": text}
                }
            ]
        }
    })

    data = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Name": {
                "title": [{"text": {"content": date_str}}]
            },
            "날짜": {
                "date": {"start": iso_date}
            },
            "태그": {
                "multi_select": [{"name": tag} for tag in tags]
            }
        },
        "children": blocks
    }

    if image_url:
        data["cover"] = {
            "type": "external",
            "external": {"url": image_url}
        }

    try:
        response = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json=data)
        if response.status_code != 200:
            logging.error(f"[NOTION ERROR] {response.status_code} - {response.text}")
            return None
        else:
            page_id = response.json().get("id")
            logging.info(f"[NOTION] 업로드 성공 (커버 포함): {page_id}")
            return page_id
    except Exception as e:
        logging.error(f"[NOTION ERROR] 업로드 실패: {e}")
        return None

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

async def upload_memory_to_notion(original_text, summary, tags=[], category="기억", status="기억 중", message_url=None):
    now = datetime.now(timezone.utc)
    iso_date = now.strftime("%Y-%m-%d")

    data = {
        "parent": { "database_id": os.getenv("NOTION_MEMORY_DB_ID") },
        "properties": {
            "기억 내용": { "title": [{"text": {"content": summary}}] },
            "전체 문장": { "rich_text": [{"text": {"content": original_text}}] },
            "카테고리": { "multi_select": [{"name": category}] },
            "태그": { "multi_select": [{"name": tag} for tag in tags] },
            "상태": { "select": {"name": status} },
        }
    }

    if message_url:
        data["properties"]["연결된 대화 ID"] = { "url": message_url }

    response = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json=data)
    if response.status_code != 200:
        logging.error(f"[NOTION MEMORY ERROR] {response.status_code} - {response.text}")
    else:
        logging.info(f"[NOTION MEMORY] 저장 성공: {response.json().get('id')}")

def fetch_pending_todos():
    now = datetime.now(KST)
    today_weekday = now.strftime("%a")
    current_time = now.time()

    response = notion.databases.query(
        database_id=TODO_DATABASE_ID,
        filter={
            "and": [
                {"property": "완료 여부", "checkbox": {"equals": False}},
                {
                    "or": [
                        {"property": "반복", "select": {"equals": "매일"}},
                        {
                            "and": [
                                {"property": "반복", "select": {"equals": "매주"}},
                                {"property": "요일", "multi_select": {"contains": today_weekday}}
                            ]
                        }
                    ]
                }
            ]
        }
    )
    
    valid_tasks = []
    for page in response["results"]:
        time_str = page["properties"].get("구체적인 시간", {}).get("rich_text", [])
        parsed_time = None
        if time_str and time_str[0]["plain_text"]:
            parsed_time = parse_time_string(time_str[0]["plain_text"])

        # 구체적인 시간이 비었거나 유효하지 않은 경우 → 시간대만 가지고 통과
        if parsed_time is None or parsed_time <= current_time:
            valid_tasks.append(page)

    print(f"[DEBUG] ✅ {len(valid_tasks)}개의 할 일이 현재 시간 기준 조건을 충족함")
    return valid_tasks

def reset_daily_todos():
    response = notion.databases.query(
        database_id=TODO_DATABASE_ID,
        # 조건 1: 매일 반복
    daily_filter = {"property": "반복", "select": {"equals": "매일"}}

    # 조건 2: 매주 반복 + 오늘 요일 포함 (조건부 생성)
    weekly_filter = {
        "and": [
            {"property": "반복", "select": {"equals": "매주"}},
            {"property": "요일", "multi_select": {"contains": today_weekday}}
        ]
    }

    # 요일 유효할 때만 or 조건에 포함
    filter_or_conditions = [daily_filter, weekly_filter]

    response = notion.databases.query(
        database_id=TODO_DATABASE_ID,
        filter={
            "and": [
                {"property": "완료 여부", "checkbox": {"equals": False}},
                {"or": filter_or_conditions}
            ]
        }
    )

    for page in response["results"]:
        page_id = page["id"]
        try:
            notion.pages.update(page_id=page_id, properties={
                "완료 여부": {"checkbox": False}
            })
            print(f"[DEBUG] ✅ {page_id} 완료 여부 초기화 완료")
        except Exception as e:
            print(f"[ERROR] ❌ {page_id} 초기화 실패: {e}")

def mark_reminder_sent(page_id, attempts=1):
    now = datetime.datetime.now(KST).isoformat()
    try:
        notion.pages.update(page_id=page_id, properties={
            "리마인드 시도 수": {"number": attempts},
            "마지막 체크 시간": {"date": {"start": now}}
        })
        print(f"[DEBUG] 🕒 리마인더 전송 기록 업데이트 완료 for {page_id}")
    except Exception as e:
        print(f"[ERROR] ❌ 리마인더 기록 실패: {e}")

def update_task_completion(page_id, done=True):
    try:
        notion.pages.update(page_id=page_id, properties={
            "완료 여부": {"checkbox": done}
        })
        logging.debug(f"[NOTION] ✅ 완료 여부 업데이트됨 (page: {page_id})")
    except Exception as e:
        logging.error(f"[NOTION] ❌ 완료 여부 업데이트 실패: {repr(e)}")
