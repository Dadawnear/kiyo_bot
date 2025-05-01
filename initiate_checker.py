import discord
from discord.ext import tasks
from datetime import datetime, timedelta
import pytz
from kiyo_brain import generate_initiate_message, fetch_recent_conversation, fetch_recent_diary, fetch_recent_observations, fetch_recent_memories
from notion_utils import get_last_active, update_last_active

# 유저 설정
USER_ID = 123456789012345678  # 실제 유저 ID로 교체
CHANNEL_ID = 987654321098765432  # 실제 채널 ID로 교체

# 시간 설정
KST = pytz.timezone('Asia/Seoul')

last_active = get_last_active()

@tasks.loop(minutes=30)
async def check_initiate_message():
    now = datetime.now(KST)
    awake_start = now.replace(hour=11, minute=0, second=0, microsecond=0)
    awake_end = (now + timedelta(days=1)).replace(hour=1, minute=0, second=0, microsecond=0)

    if not (awake_start <= now <= awake_end):
        return

    last_active = get_last_active(USER_ID)
    if not last_active:
        return

    gap = now - last_active
    gap_hours = gap.total_seconds() / 3600

    if gap_hours < 12:
        return  # 너무 짧은 공백은 무시

    # 과거 맥락 수집
    recent_chat = fetch_recent_conversation(USER_ID)
    past_diary = fetch_recent_diary()
    past_obs = fetch_recent_observations()
    past_memories = fetch_recent_memories()

    # 메시지 생성
    message = generate_initiate_message(
        gap_hours=gap_hours,
        past_diary=past_diary,
        past_obs=past_obs,
        past_memories=past_memories,
        recent_chat=recent_chat
    )

    # 메시지 전송
    channel = discord_client.get_channel(CHANNEL_ID)
    if channel:
        await channel.send(message)

# 디스코드 클라이언트는 main 파일에서 설정됨
# check_initiate_message.start()는 봇 준비 완료 후 호출 필요
