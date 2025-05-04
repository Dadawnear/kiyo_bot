import asyncio
import logging
import random
from functools import partial # partial 함수 사용 위함
from datetime import datetime

import discord
from discord.ext import commands # Bot 타입 힌트용
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError

import config # 설정 임포트
# --- Service Imports ---
# 이 파일은 여러 서비스에 의존합니다.
# from services.ai_service import AIService
# from services.notion_service import NotionService
# from services.midjourney_service import MidjourneyService
# --- Cog Imports ---
# 리마인더 버튼 View를 가져오기 위해 필요
# from bot.cogs.reminders import ReminderView
# --- Utils Imports ---
from utils.helpers import group_todos_by_timeblock # 할 일 그룹핑 헬퍼

# --- 임시 Placeholder Imports ---
# 실제 구현 전 테스트용
from services.ai_service import PlaceholderAIService as AIService
from services.notion_service import PlaceholderNotionService as NotionService
from services.midjourney_service import PlaceholderMidjourneyService as MidjourneyService
from bot.cogs.reminders import ReminderView # View는 실제 클래스 사용 가정

logger = logging.getLogger(__name__)

# --- Scheduled Job Functions ---
# 각 함수는 bot 객체를 인자로 받아 필요한 서비스에 접근합니다.

async def _get_target_user_dm(bot: commands.Bot) -> Optional[discord.DMChannel]:
    """설정된 TARGET_USER_ID로 DM 채널 객체를 가져옵니다."""
    if not config.TARGET_USER_ID:
        logger.error("Target user ID is not configured for scheduled tasks.")
        return None
    try:
        user = await bot.fetch_user(config.TARGET_USER_ID)
        if not user:
            logger.warning(f"Target user ID {config.TARGET_USER_ID} not found.")
            return None
        if not user.dm_channel:
            await user.create_dm()
            logger.info(f"Created DM channel for target user {user.name}")
        return user.dm_channel
    except discord.NotFound:
         logger.warning(f"Target user ID {config.TARGET_USER_ID} not found via fetch_user.")
         return None
    except discord.HTTPException as e:
        logger.error(f"Failed to fetch user or create DM channel: {e}")
        return None

async def _job_send_kiyo_message(bot: commands.Bot, time_context: str):
    """지정된 시간대에 키요 메시지를 사용자 DM으로 전송"""
    logger.info(f"Running scheduled Kiyo message job for '{time_context}'...")
    dm_channel = await _get_target_user_dm(bot)
    if not dm_channel: return

    # 서비스 인스턴스 가져오기 (bot 객체에 할당되었다고 가정)
    ai_service: AIService = getattr(bot, 'ai_service', AIService()) # 임시처리

    try:
        # 대화 기록 로드 (간단하게 시스템 메시지만 추가하여 응답 생성 요청)
        # 실제로는 DM 채널의 이전 대화 기록을 로드해야 함 (상태 관리 필요)
        temp_log = [("System", f"[{time_context}] 지금은 이 시간대야. 무슨 말을 할까?")]
        # 필요한 컨텍스트 (메모리, 관찰 등) 로드 로직 추가 가능
        # recent_memories = await bot.notion_service.fetch_recent_memories()

        response = await ai_service.generate_response(temp_log) # 컨텍스트 추가 전달

        if response:
            await dm_channel.send(response)
            logger.info(f"Sent scheduled Kiyo message for '{time_context}' to target user.")
            # conversation_log 업데이트 로직 필요 (bot 객체에 저장)
            # bot.add_conversation_log(dm_channel.id, "キヨ", response)
    except Exception as e:
        logger.error(f"Error in scheduled Kiyo message job for '{time_context}': {e}", exc_info=True)

async def _job_send_daily_summary(bot: commands.Bot):
    """매일 새벽, 그날의 대화를 바탕으로 일기/관찰 기록 생성 및 Notion 업로드"""
    logger.info("Running daily summary job (Diary & Observation)...")
    dm_channel = await _get_target_user_dm(bot)
    if not dm_channel: return

    # 서비스 인스턴스 가져오기
    ai_service: AIService = getattr(bot, 'ai_service', AIService())
    notion_service: NotionService = getattr(bot, 'notion_service', NotionService())
    midjourney_service: MidjourneyService = getattr(bot, 'midjourney_service', MidjourneyService())

    channel_id = dm_channel.id
    # 해당 DM 채널의 대화 기록 가져오기
    conversation_log = getattr(bot, 'conversation_logs', {}).get(channel_id, [])

    if not conversation_log:
        logger.info("No conversation log found for daily summary. Skipping diary/observation.")
        return

    # --- 1. 일기 생성 및 업로드 ---
    try:
        logger.info("Generating daily diary entry...")
        # 랜덤 스타일 선택
        styles = ["full_diary", "dream_record", "fragment", "ritual_entry"]
        chosen_style = random.choice(styles)

        diary_text = await ai_service.generate_diary_entry(conversation_log, chosen_style)
        if diary_text:
            emotion_key = await ai_service.detect_emotion(diary_text)
            # Notion 업로드 (이미지 없이)
            page_id = await notion_service.upload_diary_entry(diary_text, emotion_key, chosen_style)
            if page_id:
                # 마지막 페이지 ID 저장
                if hasattr(bot, 'last_diary_page_ids'):
                    bot.last_diary_page_ids[channel_id] = page_id
                logger.info(f"Daily diary entry created (Style: {chosen_style}, PageID: {page_id})")
                # Midjourney 이미지 요청 (오류 발생해도 다음 작업 계속)
                try:
                    image_prompt = await ai_service.generate_image_prompt(diary_text)
                    await midjourney_service.send_midjourney_prompt(bot, image_prompt)
                except Exception as mj_e:
                    logger.error(f"Failed to request Midjourney image for daily diary: {mj_e}")
            else:
                logger.error("Failed to upload daily diary entry to Notion.")
        else:
            logger.warning("Failed to generate daily diary entry text.")
    except Exception as e:
        logger.error(f"Error during daily diary generation/upload: {e}", exc_info=True)

    # --- 2. 관찰 기록 생성 및 업로드 ---
    try:
        logger.info("Generating daily observation log...")
        observation_text = await ai_service.generate_observation_log(conversation_log)
        if observation_text:
            # 제목 및 태그 생성 (Notion 서비스에서 담당한다고 가정)
            # title = await notion_service.generate_observation_title(observation_text)
            # tags = await notion_service.generate_observation_tags(observation_text)
            # 임시 제목/태그 사용
            title = f"{datetime.now(config.KST).strftime('%Y-%m-%d')} 관찰 기록"
            tags = ["자동생성", "관찰"]

            await notion_service.upload_observation(observation_text, title, tags)
            logger.info("Daily observation log created and uploaded.")
        else:
            logger.warning("Failed to generate daily observation log text.")
    except Exception as e:
        logger.error(f"Error during daily observation log generation/upload: {e}", exc_info=True)

    # --- 3. 대화 기록 초기화 ---
    if hasattr(bot, 'conversation_logs') and channel_id in bot.conversation_logs:
        bot.conversation_logs[channel_id] = []
        logger.info(f"Cleared conversation log for channel {channel_id}.")

async def _job_reset_daily_todos(bot: commands.Bot):
    """매일 자정, 반복 할 일 초기화"""
    logger.info("Running daily todo reset job...")
    notion_service: NotionService = getattr(bot, 'notion_service', NotionService())
    try:
        await notion_service.reset_daily_todos()
    except Exception as e:
        logger.error(f"Error in daily todo reset job: {e}", exc_info=True)

async def _job_check_reminders(bot: commands.Bot):
    """주기적으로 할 일 리마인더 확인 및 발송 (시간 지정된 항목)"""
    logger.info("Running scheduled reminder check job (specific time)...")
    dm_channel = await _get_target_user_dm(bot)
    if not dm_channel: return

    notion_service: NotionService = getattr(bot, 'notion_service', NotionService())
    ai_service: AIService = getattr(bot, 'ai_service', AIService())

    try:
        pending_todos = await notion_service.fetch_pending_todos()
        now = datetime.now(config.KST)

        reminders_sent = 0
        for todo in pending_todos:
            page_id = todo.get("id")
            props = todo.get("properties", {})
            title_list = props.get("할 일", {}).get("title", []) # 속성 이름 확인
            task_name = title_list[0].get("plain_text", "이름 없는 할 일") if title_list else "이름 없는 할 일"

            # 구체적인 시간 확인 및 현재 시간 이전인지 확인
            time_str_list = props.get("구체적인 시간", {}).get("rich_text", []) # 속성 이름 확인
            parsed_time = None
            if time_str_list:
                parsed_time = parse_time_string(time_str_list[0].get("plain_text", "").strip())

            # 리마인더 재전송 방지 로직 필요 (예: Notion에 '마지막 리마인드 시간' 기록 및 확인)
            # last_reminded_prop = props.get("마지막 체크 시간", {}).get("date", {}).get("start")
            # should_remind = True
            # if last_reminded_prop:
            #     # 특정 시간 이내에 리마인드 보냈으면 건너뛰기 로직 추가
            #     pass

            if parsed_time and parsed_time <= now.time(): # and should_remind:
                 logger.debug(f"Sending reminder for specific time task: '{task_name}' (Page ID: {page_id})")
                 try:
                     reminder_text = await ai_service.generate_reminder_dialogue(task_name)
                     # ReminderView 생성 (Notion 서비스 인스턴스 전달 중요)
                     view = ReminderView(notion_page_id=page_id, task_name=task_name, notion_service=notion_service)
                     await dm_channel.send(reminder_text, view=view)
                     reminders_sent += 1
                     # 리마인더 전송 기록 업데이트 (Notion에) - 필요시 구현
                     # await notion_service.mark_reminder_sent(page_id)
                     await asyncio.sleep(1) # Rate limit 방지용 짧은 대기
                 except Exception as send_e:
                      logger.error(f"Failed to send reminder for task '{task_name}' (Page ID: {page_id}): {send_e}")

        if reminders_sent > 0:
            logger.info(f"Sent {reminders_sent} specific time reminder(s).")
        else:
             logger.info("No specific time reminders to send at this time.")

    except Exception as e:
        logger.error(f"Error in reminder check job: {e}", exc_info=True)

async def _job_send_timeblock_reminder(bot: commands.Bot, timeblock: str):
    """시간대별 할 일 리마인더 발송 (시간 미지정 항목)"""
    logger.info(f"Running scheduled timeblock reminder job for '{timeblock}'...")
    dm_channel = await _get_target_user_dm(bot)
    if not dm_channel: return

    notion_service: NotionService = getattr(bot, 'notion_service', NotionService())
    ai_service: AIService = getattr(bot, 'ai_service', AIService())

    try:
        pending_todos = await notion_service.fetch_pending_todos()
        # 시간대별 그룹핑 (시간 미지정 항목만 포함하도록 수정 필요)
        # grouped = group_todos_by_timeblock(pending_todos) # utils.helpers에 구현 필요

        # 임시 그룹핑 로직: 시간 미지정 항목 필터링
        timeblock_todos = []
        for todo in pending_todos:
             props = todo.get("properties", {})
             time_str_list = props.get("구체적인 시간", {}).get("rich_text", [])
             todo_timeblock = props.get("시간대", {}).get("select", {}).get("name") # "시간대" 속성 확인
             if not time_str_list and todo_timeblock == timeblock: # 시간이 없고, 시간대가 일치하는 경우
                 title_list = props.get("할 일", {}).get("title", [])
                 task_name = title_list[0].get("plain_text", "이름 없는 할 일") if title_list else "이름 없는 할 일"
                 timeblock_todos.append(task_name)

        if timeblock_todos:
            reminder_text = await ai_service.generate_timeblock_reminder_gpt(timeblock, timeblock_todos)
            await dm_channel.send(reminder_text)
            logger.info(f"Sent timeblock reminder for '{timeblock}' with {len(timeblock_todos)} tasks.")
            # 필요시 리마인더 전송 기록 업데이트
        else:
            logger.info(f"No pending tasks found for timeblock '{timeblock}'.")

    except Exception as e:
        logger.error(f"Error in timeblock reminder job for '{timeblock}': {e}", exc_info=True)

# --- Scheduler Setup ---
# 스케줄러 인스턴스 (전역 또는 클래스 멤버로 관리 가능)
_scheduler = None

def setup_scheduler(bot: commands.Bot):
    """APScheduler 설정 및 시작"""
    global _scheduler
    if _scheduler and _scheduler.running:
        logger.warning("Scheduler is already running.")
        return

    _scheduler = AsyncIOScheduler(timezone=str(config.KST)) # timezone은 문자열로 전달
    logger.info(f"Initializing scheduler with timezone {config.KST}...")

    # --- Job 등록 ---
    try:
        # 시간대별 메시지
        _scheduler.add_job(partial(_job_send_kiyo_message, bot, "아침"), CronTrigger(hour=9, minute=0))
        _scheduler.add_job(partial(_job_send_kiyo_message, bot, "점심"), CronTrigger(hour=12, minute=0))
        _scheduler.add_job(partial(_job_send_kiyo_message, bot, "저녁"), CronTrigger(hour=18, minute=0))
        _scheduler.add_job(partial(_job_send_kiyo_message, bot, "밤"), CronTrigger(hour=23, minute=0))

        # 일일 요약 (일기/관찰)
        _scheduler.add_job(partial(_job_send_daily_summary, bot), CronTrigger(hour=2, minute=0)) # 새벽 2시

        # 할 일 초기화
        _scheduler.add_job(partial(_job_reset_daily_todos, bot), CronTrigger(hour=0, minute=1)) # 자정 1분

        # 할 일 리마인더 (시간 지정된 것) - 예: 10분마다 체크
        _scheduler.add_job(partial(_job_check_reminders, bot), CronTrigger(minute='*/10'))

        # 시간대별 리마인더
        _scheduler.add_job(partial(_job_send_timeblock_reminder, bot, "아침"), CronTrigger(hour=9, minute=5))
        _scheduler.add_job(partial(_job_send_timeblock_reminder, bot, "점심"), CronTrigger(hour=12, minute=5))
        _scheduler.add_job(partial(_job_send_timeblock_reminder, bot, "저녁"), CronTrigger(hour=18, minute=5))
        _scheduler.add_job(partial(_job_send_timeblock_reminder, bot, "밤"), CronTrigger(hour=21, minute=0))
        # '무관' 시간대 리마인더 (하루 한 번 랜덤 시간 - 예: 오후 2시 15분)
        # random_hour = random.randint(10, 21) # 10시 ~ 21시 사이
        # random_minute = random.choice([0, 15, 30, 45])
        # _scheduler.add_job(partial(_job_send_timeblock_reminder, bot, "무관"), CronTrigger(hour=random_hour, minute=random_minute))
        # 매번 실행 시 시간이 고정되므로, 다른 방식(예: 매일 자정에 다음날 실행 시간 재설정) 고려
        _scheduler.add_job(partial(_job_send_timeblock_reminder, bot, "무관"), CronTrigger(hour=14, minute=15)) # 임시 고정

        # --- 스케줄러 시작 ---
        _scheduler.start()
        logger.info("Scheduler started successfully with configured jobs.")

    except Exception as e:
        logger.exception("Failed to setup or start the scheduler:")
        if _scheduler and _scheduler.running:
            _scheduler.shutdown()
        _scheduler = None # 오류 발생 시 스케줄러 정리

def shutdown_scheduler():
    """스케줄러 종료"""
    global _scheduler
    if _scheduler and _scheduler.running:
        try:
            _scheduler.shutdown()
            logger.info("Scheduler shut down successfully.")
        except Exception as e:
            logger.error(f"Error shutting down scheduler: {e}")
        finally:
             _scheduler = None
