from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio
import logging
import os
import discord
import random

from kiyo_brain import generate_kiyo_message_with_time, generate_diary_and_image
from notion_utils import detect_emotion, upload_to_notion

# client, conversation_log, latest_image_getter를 받아서 스케줄러 초기화
def setup_scheduler(client, conversation_log, latest_image_getter, clear_image_callback):
    async def send_kiyo_message(time_context):
        try:
            logging.debug(f"[SCHEDULER] {time_context} 시각 자동 메시지 전송 시작")
            if conversation_log is not None:
                conversation_log.append(("정서영", f"[{time_context}] 시각에 자동 전송된 시스템 메시지"))
                response = await generate_kiyo_message_with_time(conversation_log, time_context)
                conversation_log.append(("キヨ", response))
                user = discord.utils.get(client.users, name=os.getenv("USER_DISCORD_NAME"))
                if user:
                    await user.send(response)
                logging.debug("[SCHEDULER] 키요 메시지 전송 완료")
        except Exception as e:
            logging.error(f"[ERROR] scheduled message error: {repr(e)}")

    async def send_daily_summary():
        try:
            logging.debug("[SCHEDULER] 일기 자동 생성 시작")
            if conversation_log:
                styles = ["full_diary", "dream_record", "fragment", "ritual_entry"]
                chosen_style = random.choice(styles)
                logging.debug(f"[SCHEDULER] 선택된 일기 스타일: {chosen_style}")

                diary_text, _ = await generate_diary_and_image(conversation_log, client, style=chosen_style)
                image_url = latest_image_getter()
                if diary_text:
                    emotion = await detect_emotion(diary_text)
                    await upload_to_notion(diary_text, emotion_key=emotion, image_url=image_url)
                    logging.debug(f"[SCHEDULER] 일기 생성 및 업로드 완료 | 스타일: {chosen_style} | 이미지: {image_url}")
                    clear_image_callback()  # 이미지 URL 초기화
                else:
                    logging.warning("[SCHEDULER] 일기 생성 실패")

                conversation_log.clear()
        except Exception as e:
            logging.error(f"[ERROR] 일기 업로드 중 오류: {repr(e)}")

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(lambda: asyncio.create_task(send_kiyo_message("morning")), CronTrigger(hour=9, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_kiyo_message("lunch")), CronTrigger(hour=12, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_kiyo_message("evening")), CronTrigger(hour=18, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_kiyo_message("night")), CronTrigger(hour=23, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_daily_summary()), CronTrigger(hour=2, minute=0))

    scheduler.start()
