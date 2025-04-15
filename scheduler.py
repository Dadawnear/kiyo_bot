# scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

def setup_scheduler():
    # 👇 이 import들을 함수 안으로 옮겨서, 실행 시점에만 가져오도록 하면 순환 참조 안 남
    from discord_bot import (
        send_morning_greeting,
        send_lunch_checkin,
        send_evening_checkin,
        send_night_checkin
    )
    from kiyo_brain import generate_diary_and_image
    from discord_bot import conversation_log

    async def send_daily_summary():
        if conversation_log:
            await generate_diary_and_image(conversation_log)
            conversation_log.clear()

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(send_morning_greeting, CronTrigger(hour=9, minute=0))
    scheduler.add_job(send_lunch_checkin, CronTrigger(hour=12, minute=0))
    scheduler.add_job(send_evening_checkin, CronTrigger(hour=18, minute=0))
    scheduler.add_job(send_night_checkin, CronTrigger(hour=23, minute=0))
    scheduler.add_job(send_daily_summary, CronTrigger(hour=2, minute=0))
    scheduler.start()
