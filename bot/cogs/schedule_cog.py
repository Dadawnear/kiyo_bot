import discord
from discord.ext import commands
import logging
from typing import Optional, TYPE_CHECKING
from datetime import datetime, time, timedelta # 오늘 날짜 기본값으로 사용 위해

import config # 설정 임포트
from utils.helpers import is_target_user, parse_natural_date_string # 헬퍼 함수 임포트

# 타입 힌트를 위해 KiyoBot 및 Service 클래스 임포트 (순환 참조 방지)
if TYPE_CHECKING:
    from bot.client import KiyoBot
    from services.ai_service import AIService
    from services.notion_service import NotionService

logger = logging.getLogger(__name__)

class ScheduleCog(commands.Cog, name="Schedule Management"):
    """사용자 메시지에서 할 일을 파싱하여 Notion 스케줄 DB에 추가하는 기능"""

    # bot 타입을 KiyoBot으로 명시
    def __init__(self, bot: 'KiyoBot'):
        self.bot = bot
        # 서비스 인스턴스 가져오기 (bot 객체에 저장된 것 사용)
        self.ai_service: 'AIService' = bot.ai_service
        self.notion_service: 'NotionService' = bot.notion_service

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """메시지 수신 시 할 일 관련 내용 파싱 및 Notion 스케줄 DB에 등록 시도"""
        # 1. 기본 필터링: 봇 자신, 다른 봇, 명령어 형식 메시지 무시
        if message.author == self.bot.user or message.author.bot:
            return
        ctx = await self.bot.get_context(message)
        if ctx.valid: # 메시지가 유효한 명령어 형식이면 여기서 처리 중단
            logger.debug(f"[ScheduleCog] Ignoring message as it's a command: {message.content[:50]}")
            return

        # 2. 대상 유저의 DM 채널에서 온 메시지만 처리
        if not (isinstance(message.channel, discord.DMChannel) and is_target_user(message.author)):
            return

        # 3. (선택적) 특정 키워드가 있는 경우에만 파싱 시도
        # if not any(kw in message.content for kw in ["할 일", "일정", "까지", "추가", "등록"]):
        #     return

        logger.debug(f"[ScheduleCog] Processing message from target user for schedule: {message.content[:50]}")

        try:
            # 4. AI 서비스로 할 일 내용 (리스트) 및 날짜 표현 추출
            extracted_info = await self.ai_service.extract_task_and_date(message.content)

            if not extracted_info or not extracted_info.get("task_descriptions"):
                logger.info(f"[ScheduleCog] No valid task descriptions extracted from: '{message.content[:50]}'")
                return

            task_descriptions_list = extracted_info["task_descriptions"] # AI는 이제 리스트를 반환
            due_date_description = extracted_info.get("due_date_description")

            if not task_descriptions_list: # AI가 빈 리스트를 반환했을 경우
                logger.info(f"[ScheduleCog] Task descriptions list is empty for: '{message.content[:50]}'")
                return

            # 5. 추출된 날짜 표현을 datetime 객체로 변환 (모든 작업에 공통 적용될 날짜)
            due_datetime: Optional[datetime] = None
            user_feedback_date_str = "날짜 미지정" # 사용자에게 보여줄 날짜 문자열

            if due_date_description:
                due_datetime = parse_natural_date_string(due_date_description)
                if due_datetime:
                    user_feedback_date_str = due_datetime.strftime('%Y년 %m월 %d일 %H:%M')
                else:
                    await message.reply(f"크크… '{due_date_description}' 날짜는 잘 모르겠네. 다시 알려줄 수 있을까?", mention_author=False)
                    logger.warning(f"[ScheduleCog] Failed to parse date string: '{due_date_description}'")
                    return
            else: # 사용자가 날짜를 언급하지 않은 경우
                now_kst = datetime.now(config.KST)
                # 기본 시간을 오전 9시로. 현재 시간이 9시 이후면 다음 날 오전 9시.
                default_task_time = time(9, 0) # from datetime import time 필요
                if now_kst.time() >= default_task_time:
                    due_datetime = (now_kst + timedelta(days=1)).replace(hour=default_task_time.hour, minute=default_task_time.minute, second=0, microsecond=0) # timedelta 임포트 필요
                    user_feedback_date_str = f"{due_datetime.strftime('%Y년 %m월 %d일 %H:%M')} (내일 기본 시간)"
                else:
                    due_datetime = now_kst.replace(hour=default_task_time.hour, minute=default_task_time.minute, second=0, microsecond=0)
                    user_feedback_date_str = f"{due_datetime.strftime('%Y년 %m월 %d일 %H:%M')} (오늘 기본 시간)"
                logger.info(f"[ScheduleCog] No due date specified, defaulting to {user_feedback_date_str} for tasks: {task_descriptions_list}")


            if not due_datetime: # 최종적으로 날짜 객체가 없으면 진행 불가
                logger.error(f"[ScheduleCog] due_datetime is None even after processing for tasks from: {message.content[:50]}")
                # 이 경우는 위에서 이미 return되었을 가능성이 높음
                return

            # --- 6. 추출된 각 할 일을 Notion에 추가 ---
            added_tasks_count = 0
            failed_tasks_count = 0
            added_task_names = [] # 성공적으로 추가된 작업 이름 목록

            for task_desc_item in task_descriptions_list:
                if not task_desc_item or not task_desc_item.strip(): # 비어있는 작업 설명은 건너뛰기
                    continue

                task_to_add = task_desc_item.strip()
                page_id = await self.notion_service.add_schedule_entry(
                    task_name=task_to_add,
                    due_date=due_datetime # 모든 작업에 동일한 due_datetime 적용
                    # completed=False 기본값 사용
                )
                if page_id:
                    added_tasks_count += 1
                    added_task_names.append(f"'{task_to_add}'") # 따옴표로 감싸서 표시
                    logger.info(f"[ScheduleCog] Successfully added schedule to Notion (Page ID: {page_id}): '{task_to_add}' for {user_feedback_date_str}")
                else:
                    failed_tasks_count += 1
                    logger.error(f"[ScheduleCog] Failed to add schedule to Notion for task: '{task_to_add}'")

            # --- 7. 사용자에게 최종 피드백 ---
            if added_tasks_count > 0:
                tasks_feedback_str = ", ".join(added_task_names)
                feedback_message = f"크크… 알겠어. 총 {added_tasks_count}개의 일정({tasks_feedback_str})을 {user_feedback_date_str}으로 Notion 캘린더에 추가해뒀지."
                if failed_tasks_count > 0:
                    feedback_message += f" (아, {failed_tasks_count}개는 추가에 실패했네.)"
            elif failed_tasks_count > 0: # 추가 성공은 없고 실패만 한 경우
                feedback_message = "크크… 일정을 Notion 캘린더에 추가하는 데 전부 실패했네."
            else: # 추가할 유효한 작업 설명이 처음부터 없었던 경우 (위에서 return 되어 여기까지 안 올 수 있음)
                feedback_message = "크크… 추가할 만한 일정을 제대로 찾지 못했어."
            
            # 실제로 작업을 시도한 경우에만 답장
            if added_tasks_count > 0 or failed_tasks_count > 0:
                await message.reply(feedback_message, mention_author=False)

        except Exception as e:
            logger.error(f"[ScheduleCog] Error processing message for schedule: {e}", exc_info=True)
            # 사용자에게 일반적인 오류 메시지를 보낼 수도 있음
            # await message.reply("크크… 요청을 처리하는 중에 문제가 생겼어.", mention_author=False)

# Cog를 봇에 추가하기 위한 필수 설정 함수
async def setup(bot: 'KiyoBot'):
    await bot.add_cog(ScheduleCog(bot))
    logger.info("ScheduleCog has been loaded.")
