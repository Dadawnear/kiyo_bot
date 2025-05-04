import asyncio
import logging
import random
from functools import partial
from datetime import datetime, time, date
from typing import Optional, TYPE_CHECKING

import discord
from discord.ext import commands # Bot 타입 힌트용
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError

import config # 설정 임포트

# --- Service Imports ---
# 실제 서비스 클래스 임포트
from services.ai_service import AIService
from services.notion_service import NotionService
from services.midjourney_service import MidjourneyService

# --- Cog Imports ---
# 리마인더 버튼 View 클래스 임포트
from bot.cogs.reminders import ReminderView

# --- Utils Imports ---
# 실제 헬퍼 함수 임포트
from utils.helpers import parse_time_string, group_todos_by_timeblock

# 타입 힌트를 위해 KiyoBot 클래스 임포트 (순환 참조 방지)
if TYPE_CHECKING:
    from bot.client import KiyoBot

logger = logging.getLogger(__name__)

# --- Scheduled Job Helper Functions ---

async def _get_target_user_dm(bot: 'KiyoBot') -> Optional[discord.DMChannel]:
    """설정된 TARGET_USER_ID로 DM 채널 객체를 안전하게 가져옵니다."""
    if not config.TARGET_USER_ID:
        logger.error("[Scheduler] Target user ID is not configured.")
        return None
    try:
        user = await bot.fetch_user(config.TARGET_USER_ID)
        if not user:
            logger.warning(f"[Scheduler] Target user ID {config.TARGET_USER_ID} not found.")
            return None
        # DM 채널이 없으면 생성 시도
        dm_channel = user.dm_channel or await user.create_dm()
        # logger.debug(f"[Scheduler] Obtained DM channel for target user {user.name}")
        return dm_channel
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
        logger.error(f"[Scheduler] Failed to fetch user or create DM channel: {e}")
        return None
    except Exception as e:
        logger.error(f"[Scheduler] Unexpected error getting target user DM: {e}", exc_info=True)
        return None

# --- Scheduled Job Implementations ---

async def _job_send_kiyo_message(bot: 'KiyoBot', time_context: str):
    """지정된 시간대에 키요 메시지를 사용자 DM으로 전송"""
    logger.info(f"[Scheduler] Running job: Send Kiyo Message ({time_context})")
    dm_channel = await _get_target_user_dm(bot)
    if not dm_channel: return

    try:
        # AI 서비스 호출 (컨텍스트 없이 시간대 정보만으로 생성)
        response = await bot.ai_service.generate_response(
            conversation_log=[("System", f"[{time_context}] 지금 시간대에 맞는 인사를 건네줘.")],
            # 필요시 최근 기억 등 추가 컨텍스트 전달 가능
            # recent_memories=await bot.notion_service.fetch_recent_memories(limit=1)
        )
        if response:
            await dm_channel.send(response)
            # 봇 응답 로그 기록 (KiyoBot 상태 관리 사용)
            bot.add_conversation_log(dm_channel.id, "キヨ", response)
            logger.info(f"[Scheduler] Sent scheduled Kiyo message for '{time_context}'.")
    except Exception as e:
        logger.error(f"[Scheduler] Error in job _job_send_kiyo_message ({time_context}): {e}", exc_info=True)

async def _job_send_daily_summary(bot: 'KiyoBot'):
    """매일 새벽, 일기 및 관찰 기록 생성/업로드"""
    logger.info("[Scheduler] Running job: Send Daily Summary (Diary & Observation)")
    dm_channel = await _get_target_user_dm(bot)
    if not dm_channel: return

    channel_id = dm_channel.id
    conversation_log = bot.get_conversation_log(channel_id) # KiyoBot 메소드 사용

    if not conversation_log:
        logger.info("[Scheduler] No conversation log found for daily summary. Skipping.")
        return

    # --- 1. 일기 생성 및 업로드 ---
    try:
        logger.info("[Scheduler] Generating daily diary entry...")
        styles = ["full_diary", "dream_record", "fragment", "ritual_entry"]
        chosen_style = random.choice(styles)
        diary_text = await bot.ai_service.generate_diary_entry(conversation_log, chosen_style)

        if diary_text:
            emotion_key = await bot.ai_service.detect_emotion(diary_text)
            page_id = await bot.notion_service.upload_diary_entry(diary_text, emotion_key, chosen_style)
            if page_id:
                bot.set_last_diary_page_id(channel_id, page_id) # KiyoBot 메소드 사용
                logger.info(f"[Scheduler] Daily diary created (Style: {chosen_style}, PageID: {page_id})")
                try:
                    image_prompt = await bot.ai_service.generate_image_prompt(diary_text)
                    await bot.midjourney_service.send_midjourney_prompt(bot, image_prompt)
                except Exception as mj_e:
                    logger.error(f"[Scheduler] Failed to request Midjourney image for daily diary {page_id}: {mj_e}")
            else:
                logger.error("[Scheduler] Failed to upload daily diary entry to Notion.")
        else:
            logger.warning("[Scheduler] Failed to generate daily diary entry text.")
    except Exception as e:
        logger.error(f"[Scheduler] Error during daily diary process: {e}", exc_info=True)

    # --- 2. 관찰 기록 생성 및 업로드 ---
    try:
        logger.info("[Scheduler] Generating daily observation log...")
        observation_text = await bot.ai_service.generate_observation_log(conversation_log)
        if observation_text:
            # 임시 제목/태그 사용 (개선 필요)
            title = f"{datetime.now(config.KST).strftime('%Y-%m-%d')} 관찰 기록"
            tags = ["자동생성", "관찰"]
            obs_page_id = await bot.notion_service.upload_observation(observation_text, title, tags)
            if obs_page_id:
                logger.info(f"[Scheduler] Daily observation log created (PageID: {obs_page_id})")
            else:
                logger.error("[Scheduler] Failed to upload daily observation log to Notion.")
        else:
            logger.warning("[Scheduler] Failed to generate daily observation log text.")
    except Exception as e:
        logger.error(f"[Scheduler] Error during daily observation log process: {e}", exc_info=True)

    # --- 3. 대화 기록 초기화 ---
    bot.clear_conversation_log(channel_id) # KiyoBot 메소드 사용

async def _job_reset_daily_todos(bot: 'KiyoBot'):
    """매일 자정, 반복 할 일 초기화"""
    logger.info("[Scheduler] Running job: Reset Daily Todos")
    try:
        await bot.notion_service.reset_daily_todos()
    except Exception as e:
        logger.error(f"[Scheduler] Error in job _job_reset_daily_todos: {e}", exc_info=True)

async def _job_check_reminders(bot: 'KiyoBot'):
    """주기적으로 할 일 리마인더 확인 및 발송 (시간 지정된 항목)"""
    logger.info("[Scheduler] Running job: Check Specific Time Reminders")
    dm_channel = await _get_target_user_dm(bot)
    if not dm_channel: return

    try:
        pending_todos = await bot.notion_service.fetch_pending_todos()
        if not pending_todos:
            logger.info("[Scheduler] No pending todos found.")
            return

        now = datetime.now(config.KST)
        today_start = datetime.combine(now.date(), time.min, tzinfo=config.KST)
        reminders_sent_count = 0

        for todo in pending_todos:
            page_id = todo.get("id")
            if not page_id: continue

            props = todo.get("properties", {})
            title_list = props.get("할 일", {}).get("title", [])
            task_name = title_list[0].get("plain_text", "...") if title_list else "..."

            # 구체적인 시간 확인
            time_str_list = props.get("구체적인 시간", {}).get("rich_text", [])
            parsed_time = None
            if time_str_list:
                parsed_time = parse_time_string(time_str_list[0].get("plain_text", "").strip())

            # 시간이 지정되었고, 현재 시간 이전인 경우 리마인드 대상
            if parsed_time and parsed_time <= now.time():
                # 리마인더 재전송 방지 로직 (Notion 속성 "마지막 리마인드" 확인)
                # Notion 속성 이름 확인 필수!
                last_reminded_prop = props.get("마지막 리마인드", {}).get("date", {})
                last_reminded_at = None
                if last_reminded_prop and last_reminded_prop.get("start"):
                     try:
                         # Notion 날짜/시간은 ISO 8601 형식 (UTC 또는 오프셋 포함)
                         last_reminded_at = datetime.fromisoformat(last_reminded_prop["start"])
                         # KST로 변환 (만약 시간대 정보가 없다면 KST로 가정)
                         if last_reminded_at.tzinfo is None:
                              last_reminded_at = config.KST.localize(last_reminded_at)
                         else:
                              last_reminded_at = last_reminded_at.astimezone(config.KST)
                     except ValueError:
                          logger.warning(f"[Scheduler] Failed to parse '마지막 리마인드' date for {page_id}: {last_reminded_prop.get('start')}")

                # 오늘 이미 리마인드를 보냈다면 건너뛰기
                if last_reminded_at and last_reminded_at >= today_start:
                    logger.debug(f"[Scheduler] Already reminded task '{task_name}' today ({last_reminded_at}). Skipping.")
                    continue

                # 리마인더 발송
                logger.info(f"[Scheduler] Sending reminder for specific time task: '{task_name}' (Page ID: {page_id})")
                try:
                    reminder_text = await bot.ai_service.generate_reminder_dialogue(task_name)
                    # ReminderView 생성 (Cog에서 임포트, NotionService 전달)
                    view = ReminderView(notion_page_id=page_id, task_name=task_name, notion_service=bot.notion_service)
                    await dm_channel.send(reminder_text, view=view)
                    reminders_sent_count += 1

                    # Notion에 리마인더 전송 시간 기록 (새로운 NotionService 메소드 필요 가정)
                    # await bot.notion_service.mark_reminder_timestamp(page_id, now)
                    logger.debug(f"[Scheduler] Reminder sent for {page_id}. Notion timestamp update needed.") # TODO

                    await asyncio.sleep(1) # Rate limit 방지
                except Exception as send_e:
                     logger.error(f"[Scheduler] Failed to send reminder for task '{task_name}' ({page_id}): {send_e}")

        logger.info(f"[Scheduler] Finished checking specific time reminders. Sent: {reminders_sent_count}")

    except Exception as e:
        logger.error(f"[Scheduler] Error in job _job_check_reminders: {e}", exc_info=True)

async def _job_send_timeblock_reminder(bot: 'KiyoBot', timeblock: str):
    """시간대별 할 일 리마인더 발송 (시간 미지정 항목)"""
    logger.info(f"[Scheduler] Running job: Send Timeblock Reminder ({timeblock})")
    dm_channel = await _get_target_user_dm(bot)
    if not dm_channel: return

    try:
        pending_todos = await bot.notion_service.fetch_pending_todos()
        if not pending_todos: return

        now_date = datetime.now(config.KST).date()
        timeblock_todos = []
        pages_to_mark = [] # 리마인더 보낸 후 상태 업데이트할 페이지 ID 목록

        for todo in pending_todos:
            page_id = todo.get("id")
            if not page_id: continue
            props = todo.get("properties", {})

            # 시간 미지정 확인
            time_str_list = props.get("구체적인 시간", {}).get("rich_text", [])
            if time_str_list and time_str_list[0].get("plain_text", "").strip():
                continue # 시간이 지정된 항목은 제외

            # 시간대 확인 ("시간대" 속성 이름 확인!)
            todo_timeblock_prop = props.get("시간대", {}).get("select")
            todo_timeblock = todo_timeblock_prop.get("name") if todo_timeblock_prop else None

            if todo_timeblock == timeblock:
                # 리마인더 재전송 방지 (Notion 속성 "오늘 리마인드" 체크박스 확인)
                # Notion 속성 이름 확인 필수!
                reminded_today_prop = props.get("오늘 리마인드", {}).get("checkbox", False)
                if reminded_today_prop:
                    logger.debug(f"[Scheduler] Already sent timeblock reminder for '{timeblock}' task {page_id} today. Skipping.")
                    continue

                title_list = props.get("할 일", {}).get("title", [])
                task_name = title_list[0].get("plain_text", "...") if title_list else "..."
                timeblock_todos.append(task_name)
                pages_to_mark.append(page_id)

        if timeblock_todos:
            reminder_text = await bot.ai_service.generate_timeblock_reminder_gpt(timeblock, timeblock_todos)
            await dm_channel.send(reminder_text)
            logger.info(f"[Scheduler] Sent timeblock reminder for '{timeblock}' with {len(timeblock_todos)} tasks.")

            # 리마인더 전송 완료 상태 업데이트 (Notion "오늘 리마인드" 체크)
            # TODO: NotionService에 체크박스 업데이트 메소드 추가 필요
            # update_tasks = [bot.notion_service.mark_timeblock_reminded(pid, True) for pid in pages_to_mark]
            # await asyncio.gather(*update_tasks, return_exceptions=True)
            logger.debug(f"[Scheduler] Timeblock reminder sent for {len(pages_to_mark)} pages. Notion update needed.") # TODO
        else:
            logger.info(f"[Scheduler] No pending tasks found for timeblock '{timeblock}' requiring reminder.")

        # 자정에 "오늘 리마인드" 체크박스 초기화 필요 (_job_reset_daily_todos 에 추가)

    except Exception as e:
        logger.error(f"[Scheduler] Error in job _job_send_timeblock_reminder ({timeblock}): {e}", exc_info=True)


# --- Scheduler Setup ---
_scheduler: Optional[AsyncIOScheduler] = None

def setup_scheduler(bot: 'KiyoBot'):
    """APScheduler 설정 및 시작"""
    global _scheduler
    if _scheduler and _scheduler.running:
        logger.warning("Scheduler is already running.")
        return

    _scheduler = AsyncIOScheduler(timezone=str(config.KST))
    logger.info(f"[Scheduler] Initializing scheduler with timezone {config.KST}...")

    try:
        # --- Job 등록 ---
        # 시간대별 메시지
        _scheduler.add_job(partial(_job_send_kiyo_message, bot, "아침"), CronTrigger(hour=9, minute=0), id="_job_send_kiyo_morning", replace_existing=True)
        _scheduler.add_job(partial(_job_send_kiyo_message, bot, "점심"), CronTrigger(hour=12, minute=0), id="_job_send_kiyo_lunch", replace_existing=True)
        _scheduler.add_job(partial(_job_send_kiyo_message, bot, "저녁"), CronTrigger(hour=18, minute=0), id="_job_send_kiyo_evening", replace_existing=True)
        _scheduler.add_job(partial(_job_send_kiyo_message, bot, "밤"), CronTrigger(hour=23, minute=0), id="_job_send_kiyo_night", replace_existing=True)

        # 일일 요약 (일기/관찰)
        _scheduler.add_job(partial(_job_send_daily_summary, bot), CronTrigger(hour=2, minute=0), id="_job_send_daily_summary", replace_existing=True) # 새벽 2시

        # 할 일 초기화
        _scheduler.add_job(partial(_job_reset_daily_todos, bot), CronTrigger(hour=0, minute=1), id="_job_reset_daily_todos", replace_existing=True) # 자정 1분

        # 할 일 리마인더 (시간 지정된 것) - 예: 5분마다 체크
        _scheduler.add_job(partial(_job_check_reminders, bot), CronTrigger(minute='*/5'), id="_job_check_reminders", replace_existing=True)

        # 시간대별 리마인더
        _scheduler.add_job(partial(_job_send_timeblock_reminder, bot, "아침"), CronTrigger(hour=9, minute=5), id="_job_tb_reminder_morning", replace_existing=True)
        _scheduler.add_job(partial(_job_send_timeblock_reminder, bot, "점심"), CronTrigger(hour=12, minute=5), id="_job_tb_reminder_lunch", replace_existing=True)
        _scheduler.add_job(partial(_job_send_timeblock_reminder, bot, "저녁"), CronTrigger(hour=18, minute=5), id="_job_tb_reminder_evening", replace_existing=True)
        _scheduler.add_job(partial(_job_send_timeblock_reminder, bot, "밤"), CronTrigger(hour=21, minute=0), id="_job_tb_reminder_night", replace_existing=True)
        _scheduler.add_job(partial(_job_send_timeblock_reminder, bot, "무관"), CronTrigger(hour=14, minute=15), id="_job_tb_reminder_misc", replace_existing=True) # 임시 고정

        # --- 스케줄러 시작 ---
        _scheduler.start()
        logger.info("[Scheduler] Scheduler started successfully.")

    except Exception as e:
        logger.exception("[Scheduler] Failed to setup or start the scheduler:")
        if _scheduler and _scheduler.running:
            _scheduler.shutdown()
        _scheduler = None

def shutdown_scheduler():
    """스케줄러 종료"""
    global _scheduler
    if _scheduler and _scheduler.running:
        try:
            _scheduler.shutdown()
            logger.info("[Scheduler] Scheduler shut down successfully.")
        except Exception as e:
            logger.error(f"[Scheduler] Error shutting down scheduler: {e}")
        finally:
             _scheduler = None
