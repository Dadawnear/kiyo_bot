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

# 시간대 순서 정의 (누적 알림용)
ORDERED_TIMEBLOCKS = ["아침", "점심", "저녁", "밤"] # Notion의 "시간대" 속성 옵션과 일치해야 함
REMINDER_COOLDOWN_HOURS = 3 # 최소 리마인더 간격 (시간)

async def _job_check_reminders(bot: 'KiyoBot'):
    """주기적으로 시간 지정된 할 일 리마인더 확인 및 발송"""
    logger.info("[Scheduler] Running job: Check Specific Time Reminders")
    dm_channel = await _get_target_user_dm(bot)
    if not dm_channel: return

    try:
        pending_todos = await bot.notion_service.fetch_pending_todos()
        if not pending_todos:
            logger.debug("[Scheduler] No pending todos found by fetch_pending_todos for specific time reminders.")
            return

        now = datetime.now(config.KST)
        reminders_sent_count = 0

        for todo in pending_todos:
            page_id = todo.get("id"); props = todo.get("properties", {})
            if not page_id: continue

            title_list = props.get("할 일", {}).get("title", [])
            task_name = title_list[0].get("plain_text", "...") if title_list else "..."

            # 구체적인 시간 확인
            time_str_list = props.get("구체적인 시간", {}).get("rich_text", [])
            if not time_str_list or not time_str_list[0].get("plain_text", "").strip():
                continue # 시간이 지정되지 않은 항목은 이 작업에서 제외

            parsed_time = parse_time_string(time_str_list[0].get("plain_text", "").strip())

            if parsed_time and parsed_time <= now.time(): # 시간이 지났다면
                # "마지막 리마인드" 시간 확인
                last_reminded_at = None
                last_reminded_prop = props.get("마지막 리마인드", {}).get("date", {})
                if last_reminded_prop and last_reminded_prop.get("start"):
                    try:
                        last_reminded_at = datetime.fromisoformat(last_reminded_prop["start"])
                        if last_reminded_at.tzinfo is None: last_reminded_at = config.KST.localize(last_reminded_at)
                        else: last_reminded_at = last_reminded_at.astimezone(config.KST)
                    except ValueError: pass

                # 최근 N시간 내에 알림 보냈으면 건너뛰기
                if last_reminded_at and (now - last_reminded_at) < timedelta(hours=REMINDER_COOLDOWN_HOURS):
                    logger.debug(f"[Scheduler] Task '{task_name}' ({page_id}) reminded recently at {last_reminded_at}. Skipping specific time reminder.")
                    continue

                logger.info(f"[Scheduler] Sending reminder for specific time task: '{task_name}' (Page ID: {page_id})")
                try:
                    reminder_text = await bot.ai_service.generate_reminder_dialogue(task_name)
                    view = ReminderView(notion_page_id=page_id, task_name=task_name, notion_service=bot.notion_service)
                    await dm_channel.send(reminder_text, view=view)
                    reminders_sent_count += 1
                    await bot.notion_service.update_task_last_reminded_at(page_id, now) # 리마인드 시간 기록
                    await asyncio.sleep(1)
                except Exception as send_e:
                     logger.error(f"[Scheduler] Failed to send reminder for task '{task_name}' ({page_id}): {send_e}")
        if reminders_sent_count > 0:
            logger.info(f"[Scheduler] Sent {reminders_sent_count} specific time reminder(s).")

    except Exception as e:
        logger.error(f"[Scheduler] Error in job _job_check_reminders: {e}", exc_info=True)


async def _job_send_timeblock_reminder(bot: 'KiyoBot', current_timeblock_name: str):
    """시간대별 누적 할 일 리마인더 발송 (시간 미지정 항목)"""
    logger.info(f"[Scheduler] Running job: Send Cumulative Timeblock Reminder for '{current_timeblock_name}'")
    dm_channel = await _get_target_user_dm(bot)
    if not dm_channel: return

    try:
        pending_todos = await bot.notion_service.fetch_pending_todos()
        if not pending_todos:
            logger.debug("[Scheduler] No pending todos found by fetch_pending_todos for timeblock reminder.")
            return

        now = datetime.now(config.KST)
        cumulative_tasks_for_reminder = [] # 이번 리마인더에 포함될 태스크 이름 목록
        pages_to_update_reminded_time = [] # 리마인더 보낸 후 "마지막 리마인드" 시간 업데이트할 페이지 ID 목록

        # 현재 시간대까지의 모든 시간대 식별
        try:
            current_timeblock_index = ORDERED_TIMEBLOCKS.index(current_timeblock_name)
            relevant_timeblocks = ORDERED_TIMEBLOCKS[:current_timeblock_index + 1]
        except ValueError:
            logger.error(f"[Scheduler] Invalid timeblock name '{current_timeblock_name}' provided.")
            return

        logger.debug(f"[Scheduler] Relevant timeblocks for '{current_timeblock_name}' reminder: {relevant_timeblocks}")

        for todo in pending_todos:
            page_id = todo.get("id"); props = todo.get("properties", {})
            if not page_id: continue

            # 시간이 지정된 항목은 제외
            time_str_list = props.get("구체적인 시간", {}).get("rich_text", [])
            if time_str_list and time_str_list[0].get("plain_text", "").strip():
                continue

            # 할 일의 "시간대" 속성 값 가져오기
            task_timeblock_prop = props.get("시간대", {}).get("select") # Notion 속성 이름 확인!
            task_timeblock = task_timeblock_prop.get("name") if task_timeblock_prop else None

            if task_timeblock and task_timeblock in relevant_timeblocks:
                # "마지막 리마인드" 시간 확인
                last_reminded_at = None
                last_reminded_prop = props.get("마지막 리마인드", {}).get("date", {})
                if last_reminded_prop and last_reminded_prop.get("start"):
                    try:
                        last_reminded_at = datetime.fromisoformat(last_reminded_prop["start"])
                        if last_reminded_at.tzinfo is None: last_reminded_at = config.KST.localize(last_reminded_at)
                        else: last_reminded_at = last_reminded_at.astimezone(config.KST)
                    except ValueError: pass

                # 최근 N시간 내에 알림 보냈으면 건너뛰기
                if last_reminded_at and (now - last_reminded_at) < timedelta(hours=REMINDER_COOLDOWN_HOURS):
                    logger.debug(f"[Scheduler] Task for timeblock '{task_timeblock}' ({page_id}) reminded recently at {last_reminded_at}. Skipping.")
                    continue

                title_list = props.get("할 일", {}).get("title", [])
                task_name = title_list[0].get("plain_text", "...") if title_list else "..."
                cumulative_tasks_for_reminder.append(task_name)
                pages_to_update_reminded_time.append(page_id)

        if cumulative_tasks_for_reminder:
            # AI 프롬프트에 현재 시간대 이름 대신 좀 더 일반적인 문구 전달 가능
            # 예: current_timeblock_display_name = f"{current_timeblock_name} (누적)"
            reminder_text = await bot.ai_service.generate_timeblock_reminder_gpt(
                current_time_display_name=f"{current_timeblock_name}까지의 현황", # AI에게 전달할 시간대 표현
                todo_titles=cumulative_tasks_for_reminder
            )
            await dm_channel.send(reminder_text) # 시간대별 누적 리마인더에는 버튼 미포함 (메시지만)
            logger.info(f"[Scheduler] Sent cumulative timeblock reminder for '{current_timeblock_name}' with {len(cumulative_tasks_for_reminder)} tasks.")

            # 리마인더 전송된 할 일들의 "마지막 리마인드" 시간 업데이트
            update_tasks = [bot.notion_service.update_task_last_reminded_at(pid, now) for pid in pages_to_update_reminded_time]
            await asyncio.gather(*update_tasks, return_exceptions=True) # 오류 발생해도 계속 진행
        else:
            logger.info(f"[Scheduler] No pending tasks found for cumulative reminder up to '{current_timeblock_name}'.")

    except Exception as e:
        logger.error(f"[Scheduler] Error in job _job_send_timeblock_reminder ({current_timeblock_name}): {e}", exc_info=True)

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
