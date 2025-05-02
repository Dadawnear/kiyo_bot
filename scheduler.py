from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio
import logging
import os
import discord
import random

from kiyo_brain import (
    generate_kiyo_message_with_time, 
    generate_diary_and_image,
    generate_timeblock_reminder_gpt
)
from notion_utils import (
    detect_emotion, 
    upload_to_notion, 
    generate_observation_log, 
    reset_daily_todos,
    fetch_pending_todos, 
    group_todos_by_timeblock
)

async def send_timeblock_reminder(bot, timeblock: str):
    todos = fetch_pending_todos()
    grouped = group_todos_by_timeblock(todos)

    # '무관'의 경우에도 처리
    if timeblock in grouped:
        reminder_text = await generate_timeblock_reminder_gpt(timeblock, grouped[timeblock])
        user = discord.utils.get(bot.users, name=os.getenv("USER_DISCORD_NAME"))
        if user:
            await user.send(reminder_text)
            logging.debug(f"[SCHEDULER] {timeblock} 리마인드 전송 완료")

# client, conversation_log, latest_image_getter, clear_image_callback를 받아서 스케줄러 초기화
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
                    clear_image_callback()
                else:
                    logging.warning("[SCHEDULER] 일기 생성 실패")

                conversation_log.clear()
        except Exception as e:
            logging.error(f"[ERROR] 일기 업로드 중 오류: {repr(e)}")

    async def send_observation_log():
        try:
            logging.debug("[SCHEDULER] 관찰일지 생성 시작")
            await generate_observation_log()
            logging.debug("[SCHEDULER] 관찰일지 생성 완료")
        except Exception as e:
            logging.error(f"[ERROR] 관찰일지 생성 중 오류: {repr(e)}")

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    loop = asyncio.get_event_loop() 
    scheduler.add_job(lambda: asyncio.create_task(send_kiyo_message("morning")), CronTrigger(hour=9, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_kiyo_message("lunch")), CronTrigger(hour=12, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_kiyo_message("evening")), CronTrigger(hour=18, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_kiyo_message("night")), CronTrigger(hour=23, minute=0))
    scheduler.add_job(lambda: reset_daily_todos(), CronTrigger(hour=0, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_daily_summary()), CronTrigger(hour=2, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_observation_log()), CronTrigger(hour=3, minute=0))

    # 아침~밤: 지정 시간
    scheduler.add_job(lambda: asyncio.create_task(send_timeblock_reminder(client, "아침")), CronTrigger(hour=9, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_timeblock_reminder(client, "점심")), CronTrigger(hour=12, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_timeblock_reminder(client, "저녁")), CronTrigger(hour=18, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_timeblock_reminder(client, "밤")), CronTrigger(hour=21, minute=0))

    # 무관: 하루에 한 번 랜덤 시간
    random_hour = random.choice(range(10, 22))
    random_minute = random.choice([0, 15, 30, 45])
    scheduler.add_job(lambda: asyncio.create_task(send_timeblock_reminder(client, "무관")), CronTrigger(hour=random_hour, minute=random_minute))

    logging.info("[SCHEDULER] 스케줄러 시작됨")
    scheduler.start()
