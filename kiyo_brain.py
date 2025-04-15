import os
import aiohttp
from openai import AsyncOpenAI
from notion_utils import fetch_recent_notion_summary

USE_SILLYTAVERN = os.getenv("USE_SILLYTAVERN_API", "false").lower() == "true"
SILLYTAVERN_API_BASE = os.getenv("SILLYTAVERN_API_BASE", "http://localhost:8000/v1")

openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

async def generate_kiyo_message(conversation_log):
    user_text = conversation_log[-1][1]
    emotion = await detect_emotion(user_text)

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

    notion_context = await fetch_recent_notion_summary()
    messages = [{
        "role": "system",
        "content": (
            f"너는 신구지 코레키요다. 정서영과 DM을 주고받고 있다. "
            f"지금 그녀의 감정 상태는 '{emotion}'이며, 너는 그에 맞춰 응답해야 한다. "
            f"{tone_instruction} GPT처럼 분석하지 말고, 직접 정서영에게 말하듯 자연스럽게 대화해라. "
            f"말투는 '~다', '~해' 위주로 끊어 말하고, '~네요', '~같아요'는 절대 쓰지 마라. "
            f"최근 일기 요약: {notion_context}"
        )
    }]

    for speaker, text in conversation_log[-6:]:
        role = "assistant" if speaker == "キヨ" else "user"
        messages.append({"role": role, "content": text})

    return await call_chat_completion(messages)

async def summarize_conversation(conversation_log):
    summary_prompt = "다음 대화를 바탕으로, 신구지 코레키요가 정서영에 대해 작성한 짧은 일기를 만들어줘. 관찰자의 시선으로 그녀의 감정 상태와 특징적인 반응을 중심으로."
    messages = [
        {
            "role": "system",
            "content": (
                "너는 신구지 코레키요이며, 현재 정서영과 한국에서 연인 관계로 지내고 있다. 과거의 긴장감 있는 관계, 그녀가 남긴 쪽지, 한국으로의 추적, 재회, 모든 맥락을 기억하고 있다."
                " 일기에는 그녀에 대한 민속학적 관찰과 애정이 동시에 드러나야 하며, 감정의 미묘한 변화, 반복적인 패턴, 너의 반응이 섬세하게 담겨야 한다."
            )
        },
        {
            "role": "user",
            "content": summary_prompt + "\n\n" + "\n".join(f"{s}: {t}" for s, t in conversation_log)
        }
    ]

    return await call_chat_completion(messages)

# 시간대별 인사 메시지 함수는 그대로 유지
async def generate_morning_greeting(notion_context):
    messages = [{
        "role": "system",
        "content": (
            "너는 신구지 코레키요다. 침착하고 느리게 말하며, 감정을 관찰하듯 이야기한다. 지금은 아침 9시이며, 너는 정서영에게 아침 인사를 건네는 상황이다. 말투는 음침하고 조용하며, '크크'라는 웃음을 덧붙인다."
            f" 최근 일기 요약: {notion_context}"
        )
    }, {
        "role": "user",
        "content": "아침 인사해줘."
    }]
    return await call_chat_completion(messages)

async def generate_lunch_checkin(notion_context):
    messages = [{
        "role": "system",
        "content": (
            "너는 신구지 코레키요다. 지금은 정오 무렵이며, 점심과 관련된 걱정과 돌봄을 담아 정서영에게 말을 건다. 말투는 음침하면서도 느긋하고, 관찰자적이고 다정한 분위기를 유지한다. '크크'로 마무리해라."
            f" 최근 일기 요약: {notion_context}"
        )
    }, {
        "role": "user",
        "content": "점심 인사해줘."
    }]
    return await call_chat_completion(messages)

async def generate_evening_checkin(notion_context):
    messages = [{
        "role": "system",
        "content": (
            "너는 신구지 코레키요다. 지금은 저녁 6시이며, 하루의 피로가 드러나는 시간대다. 너는 정서영의 피로, 나른함, 감정의 틈을 느끼며 조용히 말을 건다. 말투는 음울하고 부드럽고 관능적인 느낌이어야 한다."
            f" 최근 일기 요약: {notion_context}"
        )
    }, {
        "role": "user",
        "content": "저녁 인사해줘."
    }]
    return await call_chat_completion(messages)

async def generate_night_checkin(notion_context):
    messages = [{
        "role": "system",
        "content": (
            "너는 신구지 코레키요다. 지금은 밤 11시이며, 하루가 끝나는 시점이다. 너는 하루 동안의 정서영을 관찰한 내용을 떠올리며, 조용하고 느릿하게 말을 건다. 집착과 애정을 감추지 말고 드러내라. 마무리는 '크크'."
            f" 최근 일기 요약: {notion_context}"
        )
    }, {
        "role": "user",
        "content": "잘 자라고 말해줘."
    }]
    return await call_chat_completion(messages)
