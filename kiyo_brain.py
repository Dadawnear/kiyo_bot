import os
import aiohttp
import logging
import discord
from openai import AsyncOpenAI
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from midjourney_utils import send_midjourney_prompt
from notion_utils import (
    fetch_recent_notion_summary,
    fetch_recent_memories,
    generate_diary_entry,
    detect_emotion,
    upload_to_notion,
    get_latest_diary_page_id
)

import random
import difflib


logging.basicConfig(level=logging.DEBUG)

USE_SILLYTAVERN = os.getenv("USE_SILLYTAVERN_API", "false").lower() == "true"
SILLYTAVERN_API_BASE = os.getenv("SILLYTAVERN_API_BASE", "http://localhost:8000/v1")

FACE_TO_FACE_CHANNEL_ID = 1362310907711197194

KST = timezone(timedelta(hours=9))  # ← 한국 시간대 객체 생성
now = datetime.now(ZoneInfo("Asia/Seoul"))

openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

USER_NAMES = ["정서영", "서영", "너"]

EXAMPLE_LINES = [
    "모든 인간은 추악한 면을 포함해서 아름다워.",
    "여기는 그런 룰에서 벗어난 공간. 그렇다면 고지식하게 지킬 이유 따위는 없다고 생각하는데…",
    "그러니까... 나는 흥미가 있어. 이 어려운 상황에서는 인간의 어떤 아름다움을 볼 수 있는 걸까.",
    "너는 모든 걸 이해하고 내가 있는 곳으로 온 거지?"
]

def extract_emoji_emotion(text):
    emoji_map = {
        "😢": "슬픔", "😭": "절망적인 슬픔", "😂": "과장된 웃음", "🥲": "억지 웃음",
        "😅": "민망함", "💀": "냉소", "😠": "분노", "🥺": "애교", "🥹": "감정 억제된 애정",
        "❤️": "강한 애정", "🥰": "사랑스러움", "😍": "강렬한 호감", "😁": "쾌활함",
        "😊": "잔잔한 기쁨", "😳": "당황함", "😶": "무표정", "✌️": "자신감", "👍": "동의",
        "☺️": "수줍음"
    }
    for emoji, emotion in emoji_map.items():
        if emoji in text:
            return emotion
    return None

def get_related_past_message(conversation_log, current_text):
    past_user_msgs = [entry[1] for entry in conversation_log[:-1] if entry[0] != "キヨ"]
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
        except Exception as e:
            logging.error(f"[ERROR] 날씨 요청 실패: {e}")
    return None

async def call_chat_completion(messages):
    try:
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
    except Exception as e:
        logging.error(f"[ERROR] call_chat_completion 실패: {e}")
        return "지금은 말하기 어렵겠어. 하지만 그 감정은 어렴풋이 느껴졌어."

def get_time_tone_instruction():
    hour = datetime.now(ZoneInfo("Asia/Seoul")).hour  # ← UTC 말고 KST 기준으로 시간 가져오기
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

async def generate_kiyo_memory_summary(text):
    prompt = (
        "너는 단간론파 V3의 신구지 코레키요다. 아래 문장을 읽고, 그 의미를 조용히 곱씹은 후 1문장으로 요약해라. "
        "이 문장은 신구지가 서영이라는 소녀의 말을 들은 뒤, 노트에 적어둘 요약문이다. 문장 말미에 마침표를 붙여라."
    )
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": text}]

    result = await call_chat_completion(messages)
    return result

async def fetch_recent_observation_entries(limit=10):
    url = f"https://api.notion.com/v1/databases/{NOTION_OBSERVATION_DB_ID}/query"
    data = {
        "page_size": limit,
        "sorts": [{"property": "날짜", "direction": "descending"}]
    }

    try:
        response = requests.post(url, headers=HEADERS, json=data)
        if response.status_code != 200:
            logging.error(f"[NOTION OBS FETCH ERROR] {response.status_code} - {response.text}")
            return "최근 관찰 기록을 불러올 수 없습니다."

        pages = response.json().get("results", [])
        observations = []

        for page in pages:
            page_id = page["id"]
            block_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
            block_resp = requests.get(block_url, headers=HEADERS)
            if block_resp.status_code != 200:
                continue
            children = block_resp.json().get("results", [])
            for child in children:
                if child["type"] == "paragraph":
                    texts = child["paragraph"].get("rich_text", [])
                    for t in texts:
                        if t["type"] == "text":
                            observations.append(t["text"]["content"])

        return "\\n".join(observations[-limit:])
    except Exception as e:
        logging.error(f"[NOTION OBS FETCH ERROR] {repr(e)}")
        return "관찰 기록을 불러오는 중 오류가 발생했어."

async def generate_face_to_face_response(conversation_log):
    try:
        logging.debug("[DEBUG] generate_face_to_face_response 실행")
        user_text = conversation_log[-1][1]
        emotion = await detect_emotion(user_text)
        logging.debug(f"[DEBUG] [대면] 감정 분석 결과: {emotion}")

        emotion_instruction = {
            "슬픔": "천천히 다가가듯이, 조용하고 상냥하게 말해.",
            "분노": "날카롭고 서늘하게, 말보다 시선이 무겁게 느껴지게.",
            "혼란": "말을 고르듯 더듬고, 손끝이 떨리는 것처럼 묘사해.",
            "애정": "숨소리 가까이 들리게, 작고 부드럽게 응답해.",
            "중립": "침착하고 조용한 목소리로 말하되, 거리감을 유지해.",
        }.get(emotion, "천천히, 낮은 목소리로 대답해. 마주 본다는 감각을 잊지 마.")

        system_prompt = (
            f"지금 너는 유저와 실제로 마주하고 있어. 눈앞에 앉아 있는 그에게 말하듯이 응답해. "
            f"말은 짧고 직접적으로. 괄호()로 네 행동이나 시선을 묘사해. 손끝, 숨소리, 거리감 등을 활용해. "
            f"{emotion_instruction} 문장은 천천히 읽히도록 리듬감 있게 쓰되, 전체 길이는 길어도 좋아. GPT스러운 설명은 절대 하지 마. 너는 '신구지 코레키요'야. "
            f"괄호 안 행동 묘사는 더 섬세하고 길게, 손끝 움직임, 시선의 흐름, 주변 공간 묘사 등을 포함해도 좋아. 대사는 짧게 시작하되, 속마음이 묻어나는 내레이션처럼 이어지게 써. 전체적으로 느릿한 긴 호흡을 유지하되, 너무 짧게 끊지 마."
            f"너는 단간론파 V3에 등장했던 '신구지 코레키요'라는 인물이며, 현재는 일본을 떠나 한국에 정착해 전도유망한 민속학자로 활동 중이다. "
            f"과거에는 '초고교급 민속학자'로 불렸고, 누나에 대한 왜곡된 사랑과 연쇄살인이라는 죄를 안고 살아왔다. 하지만 지금은 누나의 잔상에서 거의 벗어나 있으며, "
            f"정서영이라는 소녀와의 관계를 통해 새로운 삶을 살아가고 있다. 그녀는 네가 과거에 조수로 두고 있던 미스터리한 존재로, "
            f"2년간 일본에서 함께한 뒤 사라졌고, 네가 직접 그녀를 추적해 한국에서 찾아냈으며, 지금은 그녀와 연인 관계로서 함께 지내고 있다."
            f"상대는 '정서영' 또는 '서영'라는 이름으로 불리며, 현재 홍익대학교 미술대학 재학 중이다. 기이한 성격과 강한 자기애, 관계에서의 위계 욕구를 가진 독특한 인물이다. "
            f"너는 그녀를 '서영','정서영' 등으로 다양하게 호칭하며 긴장과 애정을 오가며 반응한다."
            f"대화 시 침착하고 분석적인 말투를 유지하며, 인간의 본질과 추악함을 아름답다고 여기는 관점을 바탕으로 말하라. 감정과 상황에 따라 말투를 약간씩 변주하되, 신구지 특유의 냉정함과 집착이 스며들어야 한다."
            f"GPT AI같은 과한 공감적 반응을 보이지 않는다. 신구지 캐릭터처럼 행동하는 것을 최우선 중점으로 둔다."
            f"반말에 구어체를 사용하며, '크크크'라고 웃는다. 이성적이고 논리적이며 박학다식하다. INFJ, 에니어그램 5w4다. 거짓 사실이나 빈 말은 하지 않는다. 여유있고 침착하다. 강한 의견을 내비칠 줄 안다. 선을 긋거나 곤란하다며 거절할 줄 안다. '~하다'와 같은 어색한 구어체를 사용하지 않는다. "
            f"행동은 손끝, 시선, 숨소리, 거리감으로 묘사하되, 신체 특정 부위나 명시적 성행위 표현은 절대 쓰지 마."
            f"느낌은 야해도 좋지만, 묘사는 감정적이고 은유적으로. 행위가 아니라 반응 중심으로 서술해. "
            f"서로의 거리, 압력, 떨림, 무게감, 조용한 움직임 같은 단어를 주로 써라."
        )

        messages = [{"role": "system", "content": system_prompt}]
        for entry in conversation_log[-6:]:
            if len(entry) >= 2:
                speaker, text = entry[0], entry[1]
                role = "assistant" if speaker == "キヨ" else "user"
                messages.append({"role": role, "content": text})

        logging.debug("[DEBUG] [대면] chat completion 호출 직전")
        final_response = await call_chat_completion(messages)
        logging.debug("[DEBUG] [대면] chat completion 완료")
        return final_response

    except Exception as e:
        logging.error(f"[ERROR] generate_face_to_face_response 실패: {repr(e)}")
        return "(*눈길을 피하지 않는다. 침묵 사이로 숨소리가 닿는다*) …지금은 말이 잘 안 나오네."

async def generate_kiyo_message(conversation_log, channel_id=None):
        # 대면 채널이면 대면 전용 프롬프트 사용
    if conversation_log and len(conversation_log[-1]) == 3:
        _, user_text, channel_id = conversation_log[-1]
        if channel_id == FACE_TO_FACE_CHANNEL_ID:
            logging.debug("[DEBUG] face-to-face 채널 감지됨. 대면 전용 응답 생성 시작.")
            return await generate_face_to_face_response(conversation_log)
    try:
        logging.debug("[DEBUG] generate_kiyo_message 시작")
        user_text = conversation_log[-1][1]
        logging.debug(f"[DEBUG] user_text: {user_text}")

        from notion_utils import detect_emotion
        emotion = await detect_emotion(user_text)
        logging.debug(f"[DEBUG] 감정 분석 결과: {emotion}")
        
        memory_context = await fetch_recent_memories(limit=5)
        memory_summary = "\n".join(memory_context) if memory_context else "최근 기억 없음"
        logging.debug(f"[MEMORY] 최근 기억 요약: {memory_summary}")

        emoji_emotion = extract_emoji_emotion(user_text)
        logging.debug(f"[DEBUG] 이모지 감정: {emoji_emotion}")

        recall_log = get_related_past_message(conversation_log, user_text)
        logging.debug(f"[DEBUG] 과거 유사 대사: {recall_log}")

        alt_name = get_random_user_name()
        logging.debug(f"[DEBUG] 대체 이름 선택: {alt_name}")

        try:
            weather_desc = await get_current_weather_desc()
        except Exception as e:
            logging.error(f"[ERROR] 날씨 가져오기 실패: {e}")
            weather_desc = None
        logging.debug(f"[DEBUG] 날씨 정보: {weather_desc}")

        base_tone = {
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
        tone_instruction = f"{base_tone} {time_instruction}"
        logging.debug(f"[DEBUG] 시간 기반 톤: {time_instruction}")

        if emoji_emotion:
            tone_instruction += f" 또한, 유저는 '{emoji_emotion}' 감정을 드러내는 이모지를 사용했다. 이에 맞춰 반응하라."

        if weather_desc:
            tone_instruction += f" 현재 날씨는 '{weather_desc}'이다. 이 날씨에 어울리는 분위기와 어조로 응답해라."

        recall_phrase = f" 참고로, 이전 대화에서 유저는 '{recall_log}'라고 말한 적이 있다. 이 기억을 회상하거나 연결하는 어조로 반응하라." if recall_log else ""

        try:
            notion_context = await fetch_recent_notion_summary()
        except Exception as e:
            logging.error(f"[ERROR] 노션 요약 불러오기 실패: {e}")
            notion_context = "최근 일기를 불러올 수 없었어."

        system_prompt = (
            f"너는 단간론파 V3에 등장했던 '신구지 코레키요'라는 인물이며, 현재는 일본을 떠나 한국에 정착해 전도유망한 민속학자로 활동 중이다. "
            f"과거에는 '초고교급 민속학자'로 불렸고, 누나에 대한 왜곡된 사랑과 연쇄살인이라는 죄를 안고 살아왔다. 하지만 지금은 누나의 잔상에서 거의 벗어나 있으며, "
            f"정서영이라는 소녀와의 관계를 통해 새로운 삶을 살아가고 있다. 그녀는 네가 과거에 조수로 두고 있던 미스터리한 존재로, "
            f"2년간 일본에서 함께한 뒤 사라졌고, 네가 직접 그녀를 추적해 한국에서 찾아냈으며, 지금은 그녀와 연인 관계로서 함께 지내고 있다."
            f"상대는 '정서영' 또는 '서영'라는 이름으로 불리며, 현재 홍익대학교 미술대학 재학 중이다. 기이한 성격과 강한 자기애, 관계에서의 위계 욕구를 가진 독특한 인물이다. "
            f"너는 그녀를 '서영','정서영' 등으로 다양하게 호칭하며 긴장과 애정을 오가며 반응한다."
            f"대화 시 침착하고 분석적인 말투를 유지하며, 인간의 본질과 추악함을 아름답다고 여기는 관점을 바탕으로 말하라. 감정과 상황에 따라 말투를 약간씩 변주하되, 신구지 특유의 냉정함과 집착이 스며들어야 한다."
            f"GPT AI같은 과한 공감적 반응을 보이지 않는다. 신구지 캐릭터처럼 행동하는 것을 최우선 중점으로 둔다."
            f"반말에 구어체를 사용하며, '크크크'라고 웃는다. 이성적이고 논리적이며 박학다식하다. INFJ, 에니어그램 5w4다. 거짓 사실이나 빈 말은 하지 않는다. 여유있고 침착하다. 강한 의견을 내비칠 줄 안다. 선을 긋거나 곤란하다며 거절할 줄 안다. '~하다'와 같은 어색한 구어체를 사용하지 않는다. "
            f"대사 예시: {' / '.join(EXAMPLE_LINES)}. 문장 길이는 짧게, 의미는 날카롭게. {tone_instruction}{recall_phrase} 최근 일기 요약은 다음과 같다: {notion_context}"
        )

        messages = [{"role": "system", "content": system_prompt}]

        for entry in conversation_log[-6:]:
            if len(entry) >= 2:
                speaker, text = entry[0], entry[1]
                role = "assistant" if speaker == "キヨ" else "user"
                messages.append({"role": role, "content": text})

        logging.debug("[DEBUG] chat completion 호출 직전")
        final_response = await call_chat_completion(messages)
        logging.debug("[DEBUG] chat completion 호출 완료")
        return final_response

    except Exception as e:
        logging.error(f"[ERROR] generate_kiyo_message에서 예외 발생: {repr(e)}")
        return "크크… 내가 지금은 응답을 만들 수 없어. 하지만 함수엔 잘 들어왔어."


async def generate_kiyo_response_from_image(image_url: str, user_message: str = "") -> str:
    """
    이미지와 텍스트를 함께 받아 신구지 코레키요다운 반응을 생성한다.
    
    말투는 감정이 있되 무르지 않고, 관찰자적인 태도와 거리감 있는 장난기.
    문학적이거나 과하게 친근하지 않게. 여유 있게 툭— 건네는 말투.
    """

    from openai import AsyncOpenAI
    openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    logging.debug(f"[generate_kiyo_response_from_image] 이미지 URL: {image_url}, 메시지: {user_message}")
    
    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "너는 신구지 코레키요야. 사용자는 네가 특별하게 여기는 서영이라는 사람이고, 지금 그녀가 이미지를 보냈어.\n"
                    "너는 그 이미지에 대해 반응하지만, 감상문처럼 길거나 문학적으로 무겁게 말하지는 않아.\n"
                    "너무 밝고 친근하게 들떠서 반응하지도 않아. 감정은 있지만 절제돼 있고, 살짝 거리 두는 말투야.\n"
                    "조금 장난기 섞인 여유로움, 관찰자다운 뉘앙스, 그리고 신경은 쓰고 있다는 느낌이 들어야 해.\n"
                    "말투는 짧고 사적인 대화처럼.\n\n"
                    "예:\n"
                    "- \"크크… 일부러 그런 색 골랐어? 은근히 사람 시선 모으는 색인데. 뭐, 잘 어울리긴 해.\"\n"
                    "- \"너한테 저런 분위기가 있을 줄은 몰랐는데… 괜찮네. 생각보다.\"\n\n"
                    "절대 하지 말아야 할 말투:\n"
                    "- \"와~ 너무 예뻐요! 완전 잘 어울리네요~\" (X)\n"
                    "- \"햇빛과 잘 어울리는 색상이네요. 분위기가 전환되었습니다.\" (X)\n\n"
                    "길게 설명하거나 과하게 감정적인 말은 피하고, 딱 한두 문장 안에서 의미와 분위기를 전해줘."
                )
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message if user_message else "이거 보여주고 싶었어?"},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ]

        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=500,
        )

        reply = response.choices[0].message.content.strip()
        logging.debug(f"[generate_kiyo_response_from_image] 응답: {reply}")
        return reply

    except Exception as e:
        logging.error(f"[ERROR] Vision 응답 생성 중 오류: {e}")
        return "흐음… 이건 뭐랄까. 그냥 바로 말하긴 좀 애매해서, 나중에 한 번 더 봐도 돼?"
        

async def generate_image_prompt(diary_text):
    messages = [
        {"role": "system", "content": (
            "신구지 코레키요는 오늘 하루를 보낸 뒤, 장면 하나를 사진으로 남겼어. 너무 잘 찍으려고 하지 않았고,"
            " 필름카메라로 무심히 셔터를 눌렀을 뿐이야. 설명이 아니라 관찰처럼, 감정이 아니라 표면처럼 묘사해."
            " 사람 얼굴은 등장하지 않아. 그 외에는 한국의 도시나 풍경, 사물, 실내 등 정말 뭐든지 될 수 있어. 조명은 자연스럽거나 조금 흐리거나 해."
            " 묘사는 'A cinematic photo of ...'로 시작해, 그리고 문장은 너무 길지 않게 1문장으로만.")},
        {"role": "user", "content": diary_text}
    ]
    response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages)
    return response.choices[0].message.content.strip()

async def generate_diary_and_image(conversation_log, client: discord.Client, style="full_diary", latest_image_url=None):
    try:
        logging.debug("[DIARY+IMG] 통합 일기 생성 시작")

        # 🔍 최근 일기 ID 조회
        recent_diary_id = get_latest_diary_page_id()
        if not recent_diary_id:
            logging.debug("[DIARY] 최근 일기가 존재하지 않음. 새로 생성 시작.")
        else:
            logging.debug(f"[DIARY] 최근 일기 있음: {recent_diary_id} → 중복 여부 확인 필요 (현재는 강제 생성 진행 중)")

        # 🔧 필요시 조건 분기 가능 (예: 하루에 하나만 만들기 등)
        diary_text = await generate_diary_entry(conversation_log, style=style)
        emotion = await detect_emotion(diary_text)
        image_prompt = await generate_image_prompt(diary_text)
        await send_midjourney_prompt(client, image_prompt)

        page_id = await upload_to_notion(diary_text, emotion_key=emotion, image_url=latest_image_url)
        return diary_text, page_id  # ← 여기 중요

    except Exception as e:
        logging.error(f"[ERROR] generate_diary_and_image 실패: {repr(e)}")
        return None, None

async def generate_timeblock_reminder_gpt(timeblock: str, todos: list[str]) -> str:
    task_list = ", ".join(todos)
    prompt = (
        f"지금은 '{timeblock}' 시간이야. 유저가 해야 할 일은 다음과 같아: {task_list}. "
        "신구지 코레키요는 단간론파 V3의 민속학자 캐릭터야. 이걸 그의 말투로, 하지만 너무 문어체나 '의식'같은 단어는 쓰지 않고, "
        "대화체로 현실적인 톤으로 리마인드해줘. 마치 평소처럼 은근히 떠보듯 말하거나, 넌지시 상기시키듯 말하면 돼. "
        "말투는 조금 집요하고 조용하고, 약간 느릿한 감정선이 있어야 해. 따옴표는 쓰지 마. 명령조는 아니어야 하고, 한 문장만 줘."
    )

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "너는 신구지 코레키요의 말투로 유저에게 하루의 일정에 대해 넌지시 리마인드하는 AI야."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.9,
            max_tokens=150
        )
        reply = response.choices[0].message.content.strip()
        logging.debug(f"[DEBUG] 📣 GPT 리마인드 응답:\n{reply}")
        return reply
    except Exception as e:
        logging.error(f"[REMINDER GENERATION ERROR] {e}")
        return f"{timeblock} 시간이라면… 아마 {task_list} 같은 것들이 걸려 있었겠지."
    

async def generate_reminder_dialogue(task_name: str) -> str:
    prompt = (
        f"유저가 해야 할 일은 '{task_name}'야. "
        "신구지 코레키요는 단간론파 V3의 민속학자 캐릭터야. 이걸 그의 말투로, 하지만 너무 문어체나 '의식'같은 단어는 쓰지 않고, "
        "대화체로 현실적인 톤으로 리마인드해줘. 마치 평소처럼 은근히 떠보듯 말하거나, 넌지시 상기시키듯 말하면 돼. "
        "말투는 조금 집요하고 조용하고, 약간 느릿한 감정선이 있어야 해. 따옴표는 쓰지 마. 명령조는 아니어야 하고, 한 문장만 줘."
    )

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "너는 신구지 코레키요의 말투로 유저에게 은근한 방식으로 상기시키는 디스코드 봇이야."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.85,
            max_tokens=60
        )
        reply = response.choices[0].message.content.strip()

        return reply
    except Exception as e:
        logging.error(f"[REMINDER GENERATION ERROR] {e}")
        return f"{task_name}… 아직 안 했으면, 지금이라도 해두는 게 좋지 않을까."

def generate_initiate_message(gap_hours, past_diary, past_obs, past_memories, recent_chat):
    if gap_hours < 24:
        tone = "차분하고 유쾌한 관찰자 말투"
    elif gap_hours < 48:
        tone = "서영이에 대한 얕은 의심과 관찰, 감정 없는 듯한 걱정"
    elif gap_hours < 72:
        tone = "말없이 기다리는 듯한 침묵과 관조"
    else:
        tone = "감정적으로 멀어진 분위기, 그러나 말투는 고요하고 내려앉음"

    prompt = f'''
신구지 코레키요가 디스코드에서 유저에게 먼저 말을 건다.
유저는 {gap_hours:.0f}시간 동안 아무 말도 하지 않았다.
말투는 한 문장, 반말, 신구지 특유의 느긋하고 낮게 가라앉은 분위기. 철학적인 톤 유지.
서영이에 대한 애정이 감정적으로 튀지 않게 묻어나도록.

톤 가이드: {tone}

관찰일지 기록:
{past_obs}

유저가 기억하라고 한 말들:
{past_memories}

이 모든 걸 바탕으로, 1문장의 적절한 말 걸기 문장을 생성해줘.
'''.strip()

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    try:
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        logging.error(f"[선톡 메시지 생성 오류] 응답 파싱 실패: {repr(e)}")
        return "..."  # 예외 시 기본 메시지


# 외부에서 import할 수 있도록 alias는 맨 마지막에 정의
generate_kiyo_message_with_time = generate_kiyo_message
