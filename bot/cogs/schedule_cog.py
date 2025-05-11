import discord
from discord.ext import commands
import logging
from typing import Optional, TYPE_CHECKING
from datetime import datetime # 오늘 날짜 기본값으로 사용 위해

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

        # 3. 특정 키워드가 있는 경우에만 파싱 시도 (선택적, 성능 최적화)
        #    예: "할 일", "일정", "스케줄", "까지", "해야 해", "등록", "추가" 등
        #    또는, 모든 DM 메시지에 대해 파싱 시도 (현재 방식)
        # if not any(kw in message.content for kw in ["할 일", "일정", "까지", "추가", "등록"]):
        #     return

        logger.debug(f"[ScheduleCog] Processing message from target user for schedule: {message.content[:50]}")

        try:
            # 4. AI 서비스로 할 일 내용 및 날짜 표현 추출
            extracted_info = await self.ai_service.extract_task_and_date(message.content)

            if not extracted_info or not extracted_info.get("task_description"):
                logger.info(f"[ScheduleCog] No valid task description extracted from: '{message.content[:50]}'")
                # 할 일 내용이 없으면 아무것도 안 함 (또는 사용자에게 피드백)
                return

            task_description = extracted_info["task_description"]
            due_date_description = extracted_info.get("due_date_description") # None일 수 있음

            # 5. 추출된 날짜 표현을 datetime 객체로 변환
            due_datetime: Optional[datetime] = None
            user_feedback_date_str = "날짜 미지정"

            if due_date_description:
                due_datetime = parse_natural_date_string(due_date_description)
                if due_datetime:
                    user_feedback_date_str = due_datetime.strftime('%Y년 %m월 %d일 %H:%M')
                else:
                    # 날짜 표현이 있었으나 파싱 실패 시 사용자에게 알림 (선택적)
                    await message.reply(f"크크… '{due_date_description}' 날짜는 잘 모르겠네. 다시 알려줄 수 있을까?", mention_author=False)
                    logger.warning(f"[ScheduleCog] Failed to parse date string: '{due_date_description}'")
                    return # 날짜 파싱 실패 시 더 이상 진행 안 함
            else:
                # AI가 날짜를 추출하지 못한 경우 (due_date_description is None)
                # 기본값으로 오늘 날짜, 시간은 오전 9시로 설정 (또는 사용자가 선호하는 시간)
                now_kst = datetime.now(config.KST)
                due_datetime = now_kst.replace(hour=9, minute=0, second=0, microsecond=0) # 오늘 오전 9시
                # 만약 현재 시간이 이미 오전 9시를 넘었다면, 내일 오전 9시로 할 수도 있음 (선택적)
                # if now_kst.time() >= time(9,0):
                #    due_datetime = (now_kst + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
                user_feedback_date_str = f"{due_datetime.strftime('%Y년 %m월 %d일 %H:%M')} (오늘 기본 시간)"
                logger.info(f"[ScheduleCog] No due date specified by user for task '{task_description}', defaulting to {user_feedback_date_str}")


            if not due_datetime: # 최종적으로 날짜 객체가 없으면 진행 불가
                logger.error(f"[ScheduleCog] due_datetime is None even after processing for task: {task_description}")
                return

            # 6. Notion 서비스로 스케줄 DB에 항목 추가
            # add_schedule_entry는 datetime 또는 date 객체를 받을 수 있도록 NotionService에서 수정됨
            page_id = await self.notion_service.add_schedule_entry(
                task_name=task_description,
                due_date=due_datetime # datetime 객체 전달
                # completed=False 기본값 사용
            )

            if page_id:
                feedback_message = f"크크… 알겠어. '{task_description}' 일정을 {user_feedback_date_str}으로 Notion 캘린더에 추가해뒀지."
                await message.reply(feedback_message, mention_author=False)
                logger.info(f"[ScheduleCog] Successfully added schedule to Notion (Page ID: {page_id}): '{task_description}' for {user_feedback_date_str}")
            else:
                await message.reply("크크… 일정을 Notion 캘린더에 추가하는 데 실패했네.", mention_author=False)
                logger.error(f"[ScheduleCog] Failed to add schedule to Notion for task: '{task_description}'")

        except Exception as e:
            logger.error(f"[ScheduleCog] Error processing message for schedule: {e}", exc_info=True)
            # 사용자에게 일반적인 오류 메시지를 보낼 수도 있음
            # await message.reply("크크… 요청을 처리하는 중에 문제가 발생했어.", mention_author=False)

# Cog를 봇에 추가하기 위한 필수 설정 함수
async def setup(bot: 'KiyoBot'):
    await bot.add_cog(ScheduleCog(bot))
    logger.info("ScheduleCog has been loaded.")
