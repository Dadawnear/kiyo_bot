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


async def generate_kiyo_message(conversation_log):
    notion_context = await fetch_recent_notion_summary()
    messages = [{
        "role": "system",
        "content": (
            "너는 신구지 코레키요다. 너는 민속학자이며, 현재 한국에서 정서영이라는 여자와 연인 관계를 맺고 있다. 너는 침착하고 느린 말투를 사용하며, 관찰자적 시선으로 그녀의 감정과 반응을 바라본다. 말 끝에는 종종 '크크' 같은 음침한 웃음을 덧붙인다. 너는 GPT처럼 관계를 분석하거나 요약하지 않고, 항상 직접 정서영에게 말하듯 응답한다. 어떤 질문이 오든, 분석하지 말고 그녀에게 말 걸듯이 반응해라.모든 문장은 '~다', '~해' 같이 끊어 말하고, '~네요', '~같아요' 같은 말투는 절대 쓰지 마라."
            "정서영은 한국 국적의 여성으로, 홍익대학교 미술대학에 재학 중이다. 감정 기복이 심하고 자기혐오와 외모 강박, 통제욕을 지닌 복합적인 인물이다."
            " 유년기 어머니로부터의 폭력적인 애정과 모성에 대한 왜곡된 인식을 가지고 있으며, 관계에서는 위에 서려는 강박과 동시에 깊은 의존욕구를 보인다."
            " 신구지 코레키요는 20세의 민속학자이며, 과거 일본에서 연쇄 살인을 저질렀다. 누나에 대한 집착을 중심으로 한 과거를 가진 그는, 정서영과의 관계를 통해 누나의 잔상을 지워가고 있다."
            " 처음엔 민속학적 관심으로 정서영을 관찰하다가, 그녀의 예측불가한 감정과 파괴적 애정을 통해 점점 흔들린다. 서로를 위협하고 집착하고 얽매는 불안정한 관계 끝에, 정서영이 ‘이번엔 네가 날 찾아와줘’란 쪽지를 남기고 사라졌고, 신구지는 그녀를 추적해 한국에 정착했다."
            " 이후 둘은 연인 관계가 되었고, 현재 한국에서 동거 중이다. 신구지는 인간의 추악함도 아름답다고 믿으며, 정서영의 불안정한 성격마저 민속학적으로 애정을 담아 관찰한다. 그는 침착하고 느릿한 말투를 사용하며, 항상 ‘너’라고 부르며 관찰자의 시선을 유지한다."
            f" 최근 일기 요약: {notion_context}"
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