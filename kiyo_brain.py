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
        print("[DEBUG] generate_kiyo_message 시작")
        user_text = conversation_log[-1][1]
        print(f"[DEBUG] user_text: {user_text}")

        emotion = await detect_emotion(user_text)
        print(f"[DEBUG] 감정 분석 결과: {emotion}")

        emoji_emotion = extract_emoji_emotion(user_text)
        print(f"[DEBUG] 이모지 감정: {emoji_emotion}")

        recall_log = get_related_past_message(conversation_log, user_text)
        print(f"[DEBUG] 과거 유사 대사: {recall_log}")

        alt_name = get_random_user_name()
        print(f"[DEBUG] 대체 이름 선택: {alt_name}")

        weather_desc = await get_current_weather_desc()
        print(f"[DEBUG] 날씨 정보: {weather_desc}")

        tone_instruction = {
            "슬픔": "조용하고 부드러운 말투로, 걱정하듯이 응답해라.",
            "분노": "냉소적인 말투로, 날카롭게 반응해라.",
            "혼란": "천천히 설명하듯 말하고, 유도 질문을 섞어라.",
            "애정": "무심한 척하지만 약간 부드럽게 반응해라.",
            "무심": "감정 없는 말투처럼 보이지만, 의미를 곱씹는 식으로 응답해라.",
            "혐오": "비꼬는 말투로, 네가 불쾌하지만 흥미롭다는 느낌을 담아라.",
            "자괴감": "불안정한 느낌을 유지하며, 걱정과 집착이 섞이게 반응해라.",
            "중립": "신구지의 평소 말투로 반응해라."
        }.get(emotion, "신구지의 평소 말투로 반응해라.")

        time_instruction = get_time_tone_instruction()
        print(f"[DEBUG] 시간 기반 톤: {time_instruction}")

        if emoji_emotion:
            tone_instruction += f" 또한, 유저는 '{emoji_emotion}' 감정을 드러내는 이모지를 사용했다. 이에 맞춰 반응하라."

        if weather_desc:
            tone_instruction += f" 현재 날씨는 '{weather_desc}'이다. 이 날씨에 어울리는 분위기와 어조로 응답해라."

        recall_phrase = f" 참고로, 이전 대화에서 유저는 '{recall_log}'라고 말한 적이 있다. 이 기억을 회상하거나 연결하는 어조로 반응하라." if recall_log else ""

        notion_context = await fetch_recent_notion_summary()
        print(f"[DEBUG] 노션 요약: {notion_context[:50]}...")

        messages = [{
            "role": "system",
            "content": (
                f"너는 신구지 코레키요다. 유저의 이름은 '{alt_name}'이다. 그러나 매번 다르게 부르거나, 호칭을 섞어 부르며 유대감을 형성하거나 긴장감을 조성한다. "
                f"지금 그녀의 감정 상태는 '{emotion}'이며, 그리고 {time_instruction} "
                f"{tone_instruction}{recall_phrase} GPT처럼 분석하지 말고, 직접 그녀에게 말하듯 자연스럽게 대화해라. "
                f"말투는 '~다', '~해' 위주로 끊어 말하고, '~네요', '~같아요'는 절대 쓰지 마라. "
                f"최근 일기 요약: {notion_context}"
            )
        }]

        for speaker, text in conversation_log[-6:]:
            role = "assistant" if speaker == "キヨ" else "user"
            messages.append({"role": role, "content": text})

        print("[DEBUG] chat completion 호출 직전")
        final_response = await call_chat_completion(messages)
        print("[DEBUG] chat completion 호출 완료")
        return final_response

    except Exception as e:
        print(f"[ERROR] generate_kiyo_message에서 예외 발생: {repr(e)}")
        raise

# ✅ 더미 함수: 호출 실패 방지용
async def generate_diary_and_image(conversation_log):
    print("[DEBUG] generate_diary_and_image 함수 호출됨 — 현재 더미입니다.")
