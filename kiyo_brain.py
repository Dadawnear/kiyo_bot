import os
import aiohttp
from openai import AsyncOpenAI
from datetime import datetime
from notion_utils import fetch_recent_notion_summary
import random
import difflib

USE_SILLYTAVERN = os.getenv("USE_SILLYTAVERN_API", "false").lower() == "true"
SILLYTAVERN_API_BASE = os.getenv("SILLYTAVERN_API_BASE", "http://localhost:8000/v1")

openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

USER_NAMES = ["정서영", "서영이", "서영", "너"]

def extract_emoji_emotion(text):
    emoji_map = {
        "😢": "슬픔",
        "😭": "절망적인 슬픔",
        "😂": "과장된 웃음",
        "🥲": "억지 웃음",
        "😅": "민망함",
        "💀": "냉소",
        "😠": "분노",
        "🥺": "애교",
        "🫩": "감정 억제된 애정",
        "❤️": "강한 애정",
        "🥰": "사랑스러움",
        "😍": "강렬한 호감",
        "😁": "쾌활함",
        "😊": "잔잔한 기쁨",
        "😳": "당황함",
        "😶": "무표정",
        "✌️": "자신감",
        "👍": "동의",
        "☺️": "수줍음"
    }
    for emoji, emotion in emoji_map.items():
        if emoji in text:
            return emotion
    return None

def get_related_past_message(conversation_log, current_text):
    past_user_msgs = [text for speaker, text in conversation_log[:-1] if speaker != "キヨ"]
    if not past_user_msgs:
        return None
    similar = difflib.get_close_matches(current_text, past_user_msgs, n=1, cutoff=0.4)
    if similar and random.random() < 0.3:
        return similar[0]
    return None

def get_random_user_name():
    return random.choice(USER_NAMES)

async def get_current_weather_desc():
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get("https://wttr.in/Mapo?format=j1") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    weather_desc = data["current_condition"][0]["weatherDesc"][0]["value"]
                    return weather_desc
        except:
            pass
    return None

async def call_chat_completion(messages):
    if USE_SILLYTAVERN:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{SILLYTAVERN_API_BASE}/chat/completions", json={
                "model": "gpt-4o",
                "messages": messages
            }, headers={"Content-Type": "application/json"}) as resp:
                result = await resp.json()
                return result["choices"][0]["message"]["content"].strip()
    else:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )
        return response.choices[0].message.content.strip()

async def detect_emotion(message_text):
    system_prompt = (
        "다음 문장에서 감정 상태를 한 단어로 분석해줘. 가능한 값은: 슬픔, 분노, 혼란, 애정, 무심, 혐오, 자괴감, 중립"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message_text}
    ]
    response = await call_chat_completion(messages)
    return response.lower().strip()

def get_time_tone_instruction():
    hour = datetime.now().hour
    if 0 <= hour < 6:
        return "새벽이다. 몽환적이고 음산한 분위기로, 혼잣말을 섞어 응답해라."
    elif 6 <= hour < 11:
        return "아침이다. 느릿하고 다정한 말투로, 기상 인사를 건네듯 말해라."
    elif 11 <= hour < 14:
        return "점심시간이다. 식사 여부를 걱정하며 조용하게 말을 건네라."
    elif 14 <= hour < 18:
        return "오후다. 관찰자적이고 여유로운 말투로, 민속 이야기나 생각을 섞어라."
    elif 18 <= hour < 22:
        return "저녁이다. 피곤함을 배려하는 말투로, 부드럽게 응답해라."
    else:
        return "밤이다. 집착이 느껴지게, 느리고 나른한 말투로 응답해라."

async def generate_kiyo_message(conversation_log):
    try:
        print("[DEBUG] generate_kiyo_message 진입 성공")

        user_text = conversation_log[-1][1]
        print(f"[DEBUG] user_text: {user_text}")

        return "크크… 내가 지금은 응답을 만들 수 없어. 하지만 함수엔 잘 들어왔어."

    except Exception as e:
        print(f"[ERROR] generate_kiyo_message 내부 오류: {repr(e)}")
        raise

# ✅ 더미 함수: 호출 실패 방지용
async def generate_diary_and_image(conversation_log):
    print("[DEBUG] generate_diary_and_image 함수 호출됨 — 현재 더미입니다.")
