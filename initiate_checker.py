import discord
from discord.ext import tasks
from datetime import datetime, timedelta
import pytz
import os
import logging

from kiyo_brain import (
    generate_initiate_message,
    fetch_recent_observation_entries,
    generate_kiyo_memory_summary
)
from notion_utils import get_last_active
from dotenv import load_dotenv

# === 설정 ===
USER_ID = int(os.getenv("USER_ID"))
KST = pytz.timezone('Asia/Seoul')

# === 주기적 선톡 검사 ===
@tasks.loop(minutes=30)
async def check_initiate_message(discord_client):
    now = datetime.now(KST)
    logging.debug(f"[선톡체크] 현재 시각: {now}")

    if not (now.hour >= 11 or now.hour <= 1):  # 11시~새벽 1시 사이가 아니면 종료
        logging.debug("[선톡체크] 현재는 선톡 허용 시간대가 아님")
        return

    try:
        user = await discord_client.fetch_user(USER_ID)
        if not user:
            logging.warning(f"[선톡체크] 유저를 찾을 수 없음")
            return

        last_active = get_last_active()
        logging.debug(f"[선톡체크] 마지막 유저 활동 시각: {last_active}")

        if not last_active:
            logging.debug("[선톡체크] 마지막 활동 기록이 없음")
            return

        gap = now - last_active
        gap_hours = gap.total_seconds() / 3600
        logging.debug(f"[선톡체크] 공백 시간: {gap_hours:.2f}시간")

        if gap_hours < 12:
            logging.debug("[선톡체크] 공백 시간이 12시간 미만이라 무시")
            return

        # 과거 맥락 수집
        logging.debug("[선톡체크] 과거 맥락 수집 시작")
        past_obs = fetch_recent_observation_entries(user.id)
        past_memories = generate_kiyo_memory_summary(user.id)
        logging.debug("[선톡체크] 과거 맥락 수집 완료")

        # 메시지 생성
        message = generate_initiate_message(
            gap_hours=gap_hours,
            past_memories=past_memories,
            past_obs=past_obs
        )
        logging.debug(f"[선톡체크] 생성된 메시지: {message}")

        # 메시지 전송
        user = await discord_client.fetch_user(USER_ID)
        if user:
            dm_channel = await user.create_dm()
            await dm_channel.send(message)
            logging.info("[선톡체크] DM 메시지 전송 완료")
        else:
            logging.warning("[선톡체크] 유저를 찾을 수 없음")


    except Exception as e:
        logging.error(f"[선톡체크] 오류 발생: {repr(e)}")

# check_initiate_message.start()는 봇 준비 이후에 main에서 호출해줘야 함
