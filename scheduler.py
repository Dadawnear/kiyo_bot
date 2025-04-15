from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio

def setup_scheduler():
    from discord_bot import (
        send_morning_greeting,
        send_lunch_checkin,
        send_evening_checkin,
        send_night_checkin,
        conversation_log
    )
    from kiyo_brain import generate_diary_and_image

    # 비동기 함수는 별도 태스크로 실행해야 함
    def run_async_task(coro):
        asyncio.create_task(coro)

    def schedule_daily_summary():
        if conversation_log:
            run_async_task(generate_diary_and_image(conversation_log))
            conversation_log.clear()

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(send_morning_greeting, CronTrigger(hour=9, minute=0))       # 09:00
    scheduler.add_job(send_lunch_checkin, CronTrigger(hour=12, minute=0))         # 12:00
    scheduler.add_job(send_evening_checkin, CronTrigger(hour=18, minute=0))       # 18:00
    scheduler.add_job(send_night_checkin, CronTrigger(hour=23, minute=0))         # 23:00
    scheduler.add_job(schedule_daily_summary, CronTrigger(hour=2, minute=0))      # 02:00
    scheduler.start()
