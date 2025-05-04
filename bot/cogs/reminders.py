import discord
from discord.ext import commands
from discord import ui # Discord UI Kit (Buttons, Selects, etc.)
import logging
from typing import TYPE_CHECKING

import config # 설정 임포트

# --- Service Imports ---
# 실제 NotionService 임포트
from services.notion_service import NotionService

# 타입 힌트를 위해 KiyoBot 클래스 임포트 (순환 참조 방지)
if TYPE_CHECKING:
    from bot.client import KiyoBot

logger = logging.getLogger(__name__)

# --- Reminder View Definition ---

class ReminderView(ui.View):
    """
    할 일 리마인더 메시지에 첨부될 View 클래스. "완료" 버튼을 포함합니다.
    Notion 페이지 ID와 태스크 이름, Notion 서비스 인스턴스를 저장합니다.
    """
    # 이 View는 메시지가 전송될 때 동적으로 생성됩니다.
    # notion_service 인스턴스는 Cog에서 주입받습니다.
    def __init__(self, notion_page_id: str, task_name: str, notion_service: NotionService):
        # timeout=None: 봇이 재시작해도 버튼 상호작용을 받을 수 있게 함 (단, View 객체 자체는 재생성 필요)
        super().__init__(timeout=None)
        self.notion_page_id = notion_page_id
        self.task_name = task_name
        # NotionService 인스턴스를 View 내에서 사용할 수 있도록 저장
        self.notion_service = notion_service

        # 버튼 라벨 설정 (최대 80자)
        button_label = f"'{task_name[:50]}{'...' if len(task_name) > 50 else ''}' 완료"
        # Custom ID: 봇 재시작 후에도 버튼을 식별하는 데 사용될 수 있음 (최대 100자)
        # 페이지 ID가 충분히 고유하므로 그대로 사용
        done_button_custom_id = f"reminder_done_{notion_page_id}"

        # View에 버튼 추가
        self.add_item(ReminderDoneButton(
            page_id=notion_page_id,
            task_name=task_name,
            notion_service=self.notion_service, # 버튼에도 서비스 전달
            label=button_label,
            custom_id=done_button_custom_id
        ))
        # 필요시 다른 버튼(예: 스누즈) 추가 가능

class ReminderDoneButton(ui.Button['ReminderView']): # View 타입을 명시하여 self.view 타입 힌트 가능
    """
    리마인더의 "완료" 버튼 클래스
    """
    def __init__(self, *, page_id: str, task_name: str, notion_service: NotionService, label: str, custom_id: str):
        # 버튼 스타일: success (초록색)
        super().__init__(label=label, style=discord.ButtonStyle.success, custom_id=custom_id)
        self.notion_page_id = page_id
        self.task_name = task_name
        self.notion_service = notion_service # NotionService 인스턴스 저장

    async def callback(self, interaction: discord.Interaction):
        """사용자가 '완료' 버튼을 클릭했을 때 호출되는 콜백 함수"""
        # 클릭한 사용자가 대상 유저인지 확인 (선택적이지만 권장)
        if not interaction.user or not config.TARGET_USER_ID or interaction.user.id != config.TARGET_USER_ID:
            await interaction.response.send_message("크크… 다른 사람의 할 일을 완료할 수는 없어.", ephemeral=True)
            return

        logger.info(f"Reminder 'Done' button clicked by {interaction.user} for task '{self.task_name}' (Page ID: {self.notion_page_id})")

        # 상호작용 defer (Notion API 호출이 지연될 수 있으므로)
        # ephemeral=True: "명령 실행 중..." 메시지가 클릭한 사용자에게만 보임
        await interaction.response.defer(ephemeral=True, thinking=True) # thinking=True: 로딩 아이콘 표시

        try:
            # Notion 서비스 호출하여 완료 처리
            success = await self.notion_service.update_task_completion(self.notion_page_id, True)

            if success:
                # 성공 시 사용자에게 피드백 (followup 사용)
                success_message = f"크크… '{self.task_name}' 완료 처리했어. 잘했네."
                await interaction.followup.send(success_message, ephemeral=True)

                # 원래 메시지의 버튼 비활성화 및 레이블 변경
                self.disabled = True
                self.style = discord.ButtonStyle.secondary # 회색으로 변경
                self.label = f"✅ '{self.task_name[:50]}{'...' if len(task_name) > 50 else ''}' 완료됨"
                # self.view는 이 버튼이 속한 ReminderView 객체
                # View의 모든 버튼을 비활성화 하려면 반복문 사용
                # for item in self.view.children:
                #     if isinstance(item, ui.Button): item.disabled = True
                try:
                    # 원래 상호작용 메시지를 수정
                    await interaction.edit_original_response(view=self.view)
                    logger.debug(f"Disabled button for task '{self.task_name}' on message {interaction.message.id}")
                except discord.HTTPException as edit_e:
                    logger.warning(f"Could not edit original reminder message ({interaction.message.id}) after completion: {edit_e}")
            else:
                # Notion 업데이트 실패 시 (서비스 함수가 False 반환)
                 error_message = f"크크… '{self.task_name}' 완료 처리를 Notion에 반영하는 데 실패했어."
                 await interaction.followup.send(error_message, ephemeral=True)

        except Exception as e:
            # Notion 서비스 호출 중 예외 발생 시
            logger.error(f"Error occurred during task completion update for page {self.notion_page_id}: {e}", exc_info=True)
            error_message = f"크크… '{self.task_name}' 완료 처리 중 오류가 발생했어."
            try:
                # followup.send는 defer 후에만 사용 가능
                await interaction.followup.send(error_message, ephemeral=True)
            except discord.HTTPException:
                pass # 후속 메시지 전송조차 실패하는 경우

# --- Cog Definition ---
class RemindersCog(commands.Cog, name="Reminders"):
    """할 일 리마인더 상호작용 (버튼 클릭 등) 처리"""

    # bot 타입을 KiyoBot으로 명시
    def __init__(self, bot: 'KiyoBot'):
        self.bot = bot
        # Notion 서비스 인스턴스 가져오기 (실제 서비스 사용)
        self.notion_service: NotionService = bot.notion_service
        # Cog 로드 시 View를 등록할 수도 있으나 (persistent views),
        # 여기서는 리마인더 메시지 전송 시 View 객체를 생성하여 첨부하는 방식을 사용합니다.

    # 이 Cog는 버튼 콜백으로 주로 작동하므로 별도의 명령어/리스너가 없을 수 있음


# Cog를 봇에 추가하기 위한 필수 설정 함수
async def setup(bot: 'KiyoBot'):
    await bot.add_cog(RemindersCog(bot))
    logger.info("RemindersCog has been loaded.")
