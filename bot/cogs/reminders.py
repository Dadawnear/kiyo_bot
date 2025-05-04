import discord
from discord.ext import commands
from discord import ui # Discord UI Kit (Buttons, Selects, etc.)
import logging

import config

# --- Service Imports ---
# from services.notion_service import NotionService

# --- 임시 Service Placeholder ---
class PlaceholderNotionService:
    async def update_task_completion(self, page_id: str, is_done: bool):
        status = "Done" if is_done else "Not Done"
        logger.info(f"Notion task {page_id} completion updated to {status} (Placeholder)")
        # 실제 구현 시 오류 발생 가능성 있음 (예: 페이지 없음, API 오류)
        # raise Exception("Simulated Notion API error") # 테스트용 오류 발생

# --- Logger ---
logger = logging.getLogger(__name__)

# --- Reminder View Definition ---

class ReminderView(ui.View):
    """
    할 일 리마인더 메시지에 첨부될 View 클래스. "완료" 버튼을 포함합니다.
    """
    def __init__(self, notion_page_id: str, task_name: str, notion_service):
        super().__init__(timeout=None) # timeout=None으로 설정하여 버튼이 영구적으로 작동하도록 함
        self.notion_page_id = notion_page_id
        self.task_name = task_name
        self.notion_service = notion_service # Notion 서비스 인스턴스 저장

        # 버튼 라벨 설정 (너무 길지 않게)
        button_label = f"'{task_name[:20]}{'...' if len(task_name) > 20 else ''}' 완료"
        # Custom ID 설정 (View 재시작 시 버튼 식별용)
        done_button_custom_id = f"reminder_done_{notion_page_id}"

        # 자식 요소(버튼) 추가
        self.add_item(ReminderDoneButton(
            page_id=notion_page_id,
            task_name=task_name,
            notion_service=self.notion_service,
            label=button_label,
            custom_id=done_button_custom_id
        ))
        # 필요하다면 "나중에" 또는 "스누즈" 버튼 추가 가능
        # self.add_item(ReminderSnoozeButton(...))

class ReminderDoneButton(ui.Button):
    """
    리마인더의 "완료" 버튼 클래스
    """
    def __init__(self, page_id: str, task_name: str, notion_service, label: str, custom_id: str):
        super().__init__(label=label, style=discord.ButtonStyle.success, custom_id=custom_id)
        self.notion_page_id = page_id
        self.task_name = task_name
        self.notion_service = notion_service

    async def callback(self, interaction: discord.Interaction):
        """사용자가 '완료' 버튼을 클릭했을 때 호출되는 함수"""
        logger.info(f"Reminder 'Done' button clicked by {interaction.user} for task '{self.task_name}' (Page ID: {self.notion_page_id})")

        # 1. 사용자에게 상호작용 수신 확인 메시지 표시 (Defer)
        #    Notion 업데이트가 오래 걸릴 수 있으므로 먼저 응답하는 것이 좋음
        await interaction.response.defer(ephemeral=True) # ephemeral=True: 클릭한 사용자에게만 보임

        try:
            # 2. Notion 서비스 호출하여 작업 완료 처리
            await self.notion_service.update_task_completion(self.notion_page_id, True)

            # 3. 성공 메시지 전송 (Defer 후에는 follow-up 사용)
            success_message = f"크크… '{self.task_name}' 완료 처리했어. 잘했네."
            await interaction.followup.send(success_message, ephemeral=True)

            # 4. (선택적) 원래 리마인더 메시지 수정하여 버튼 비활성화 또는 메시지 변경
            try:
                # 버튼 비활성화
                self.disabled = True
                self.style = discord.ButtonStyle.secondary # 스타일 변경
                self.label = f"✅ '{self.task_name[:20]}{'...' if len(task_name) > 20 else ''}' 완료됨"
                # View의 다른 버튼들도 필요하면 비활성화 (view = self.view)
                # for item in self.view.children:
                #    if isinstance(item, ui.Button):
                #        item.disabled = True
                await interaction.edit_original_response(view=self.view)
                logger.debug(f"Disabled button for task '{self.task_name}' on message {interaction.message.id}")
            except discord.HTTPException as edit_e:
                # 메시지를 찾을 수 없거나 수정 권한이 없는 등 예외 처리
                logger.warning(f"Could not edit original reminder message ({interaction.message.id}) after completion: {edit_e}")

        except Exception as e:
            # 5. Notion 업데이트 실패 시 오류 메시지 전송
            logger.error(f"Failed to update Notion task completion for page {self.notion_page_id}: {e}", exc_info=True)
            error_message = f"크크… '{self.task_name}' 완료 처리를 Notion에 반영하는 데 실패했어."
            try:
                await interaction.followup.send(error_message, ephemeral=True)
            except discord.HTTPException:
                # 후속 메시지 전송조차 실패하는 경우
                pass


class RemindersCog(commands.Cog, name="Reminders"):
    """할 일 리마인더 상호작용 (버튼 클릭 등) 처리"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # --- 서비스 인스턴스 주입 ---
        # self.notion_service: NotionService = bot.notion_service
        self.notion_service = PlaceholderNotionService() # 임시 Placeholder 사용

        # View는 봇이 재시작해도 계속 작동해야 하므로, Cog 초기화 시 View를 등록합니다.
        # timeout=None으로 설정된 View는 봇 재시작 후에도 이전에 보내진 메시지의 버튼 클릭을 감지할 수 있습니다.
        # 단, custom_id를 기반으로 View 객체를 다시 연결해주어야 할 수 있습니다.
        # discord.py는 View의 상태(어떤 버튼이 눌렸는지 등)를 저장하지 않으므로,
        # 상태 저장이 필요하면 외부 DB 등을 사용해야 합니다.
        # 여기서는 간단하게, 봇이 실행되는 동안 View가 유지된다고 가정합니다.
        # 만약 봇 재시작 후에도 버튼이 완벽하게 작동하게 하려면,
        # on_ready 등에서 persistent view를 등록하는 로직이 필요할 수 있습니다.
        # self.bot.add_view(ReminderView(notion_page_id="*", task_name="*", notion_service=self.notion_service))
        # 위 방식보다는, 필요 시점에 View 객체를 생성하여 메시지에 첨부하는 것이 일반적입니다.


    # 이 Cog는 주로 View와 Button 콜백으로 상호작용을 처리하므로,
    # 별도의 on_message 리스너나 명령어가 필요 없을 수 있습니다.
    # 만약 리마인더 관련 명령어가 필요하다면 여기에 추가합니다.


# Cog를 봇에 추가하기 위한 필수 설정 함수
async def setup(bot: commands.Bot):
    # 여기에 ReminderView를 persistent view로 등록하는 로직을 추가할 수 있습니다.
    # 하지만 실제 메시지 전송 시 View 객체를 생성하는 것이 더 일반적이므로 여기서는 생략합니다.
    await bot.add_cog(RemindersCog(bot))
    logger.info("RemindersCog has been loaded.")
