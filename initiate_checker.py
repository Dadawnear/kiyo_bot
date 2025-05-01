import asyncio
from datetime import datetime, timedelta
import pytz
from discord import TextChannel
from kiyo_brain import generate_korekiyo_response
from notion_utils import fetch_recent_memories

# 이 함수는 디스코드 봇 인스턴스에서 주기적으로 호출되어야 함
def should_initiate_conversation(last_user_message_time: datetime, now: datetime) -> bool:
    # 유저가 보낸 마지막 메시지 이후 6시간 이상이 지나야 함
    if not last_user_message_time:
        return False

    elapsed = now - last_user_message_time
    if elapsed < timedelta(hours=6):
        return False

    # 보낼 수 있는 시간대: 오전 11시 ~ 새벽 1시
    if now.hour < 11 and now.hour >= 2:
        return False

    return True


async def check_and_initiate(client, user_id: int, channel_id: int, get_last_user_message_time):
    channel: TextChannel = client.get_channel(channel_id)
    if not channel:
        print("[선톡] 채널을 찾을 수 없습니다.")
        return

    # 현재 시간
    now = datetime.now(pytz.timezone("Asia/Seoul"))

    # 마지막 유저 메시지 시간 받아오기
    last_user_msg_time = await get_last_user_message_time(user_id)

    if should_initiate_conversation(last_user_msg_time, now):
        print("[선톡] 조건 충족. 신구지가 먼저 말을 겁니다.")

        # 최근 기억 불러오기
        recent_memories = fetch_recent_memories(user_id=user_id)

        # 공백 시간 길이에 따라 감정 태도 조절
        emotion_hint = "장시간 침묵" if (now - last_user_msg_time).total_seconds() > 36000 else "가벼운 걱정"

        # 선톡 메시지 생성
        prompt = f"유저가 오랜 시간 대화를 하지 않았어. '{emotion_hint}'이라는 감정을 바탕으로, 최근 기억을 반영해서 신구지가 먼저 자연스럽게 말을 거는 메시지를 작성해줘."
        message = generate_korekiyo_response(prompt, recent_memories)

        await channel.send(message)
    else:
        print("[선톡] 조건 불충족. 아무 일도 하지 않습니다.")
