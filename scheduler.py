from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio
import logging
import os
import discord
from kiyo_brain import generate_kiyo_message_with_time, generate_diary_and_image

# 스케줄러가 client와 conversation_log를 인자로 받아야 순환참조 피할 수 있음
def setup_scheduler(client, conversation_log):

    async def send_kiyo_message(time_context):
        try:
            if conversation_log is not None:
                conversation_log.append(("정서영", f"[{time_context}] 시각에 자동 전송된 시스템 메시지"))
                response = await generate_kiyo_message_with_time(conversation_log, time_context)
                conversation_log.append(("キヨ", response))
                user = discord.utils.get(client.users, name=os.getenv("USER_DISCORD_NAME"))
                if user:
                    await user.send(response)
        except Exception as e:
            logging.error(f"[ERROR] scheduled message error: {repr(e)}")

    async def send_daily_summary():
        try:
            if conversation_log:
                await generate_diary_and_image(conversation_log)
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
