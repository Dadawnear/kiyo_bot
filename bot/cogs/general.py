import discord
from discord.ext import commands
import logging
import re

import config # 설정 임포트
from utils.activity_tracker import update_last_active # 유틸리티 임포트

logger = logging.getLogger(__name__)

class GeneralCog(commands.Cog):
    """봇의 일반적인 기능 및 이벤트 처리를 담당하는 Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # conversation_log는 전역 상태였으므로, 여기서 직접 관리하거나
        # bot 인스턴스 속성으로 옮겨서 관리하는 리팩토링이 필요합니다.
        # 우선은 이 Cog에서는 직접 참조하지 않도록 설계합니다.
        # self.conversation_log = bot.conversation_log # 만약 bot 객체에 log를 붙였다면

    # --- Helper Functions ---
    def is_target_user(self, author: discord.User | discord.Member) -> bool:
        """명령어나 메시지 발신자가 설정된 대상 유저인지 확인"""
        if config.TARGET_USER_ID:
            return author.id == config.TARGET_USER_ID
        elif config.TARGET_USER_DISCORD_NAME:
            # TARGET_USER_DISCORD_NAME 형식은 'username#discriminator'
            return str(author) == config.TARGET_USER_DISCORD_NAME
        else:
            logger.warning("Target user not configured. Allowing command from anyone.")
            return True # 타겟 유저 설정 없으면 일단 모두 허용 (주의!)

    # --- Commands ---
    @commands.command(name='cleanup', help='봇이 최근에 보낸 메시지를 지정한 개수만큼 삭제합니다. (대상 유저만 사용 가능)')
    async def cleanup_messages(self, ctx: commands.Context, limit: int = 1):
        """봇의 최근 메시지를 삭제하는 명령어 (!cleanup [개수])"""
        if not self.is_target_user(ctx.author):
            # 대상 유저가 아니면 반응하지 않음 (또는 거부 메시지 전송)
            logger.debug(f"Cleanup command ignored from non-target user: {ctx.author}")
            return

        if limit <= 0:
            await ctx.send("크크… 1 이상의 숫자를 알려줘야 해.", delete_after=10)
            return
        if limit > 50: # 너무 많은 메시지 삭제 방지
             await ctx.send("크크… 한 번에 너무 많이 지우려는 것 같아. 50개 이하로 해줘.", delete_after=10)
             return

        try:
            # 명령어 메시지 먼저 삭제
            await ctx.message.delete()
        except discord.Forbidden:
            logger.warning("Missing permissions to delete the command message.")
        except discord.NotFound:
            pass # 이미 삭제된 경우 무시

        deleted_count = 0
        try:
            # 채널 기록을 거슬러 올라가며 봇 메시지 삭제
            async for message in ctx.channel.history(limit=limit * 5): # 삭제할 개수보다 넉넉히 가져옴
                if message.author == self.bot.user:
                    try:
                        await message.delete()
                        deleted_count += 1
                        logger.debug(f"Deleted bot message: {message.id} in channel {ctx.channel.id}")
                        if deleted_count >= limit:
                            break # 요청한 개수만큼 삭제 완료
                    except discord.Forbidden:
                        logger.warning(f"Missing permissions to delete message {message.id}.")
                        break # 권한 없으면 중단
                    except discord.HTTPException as e:
                        logger.error(f"Failed to delete message {message.id}: {e}")

            # 삭제 결과 메시지 (잠시 후 자동 삭제)
            await ctx.send(f"크크… 내 메시지 {deleted_count}개를 정리했어.", delete_after=5)
            logger.info(f"Cleaned up {deleted_count} bot messages in channel {ctx.channel.id} by {ctx.author}")

            # 중요: conversation_log 처리
            # 이전 코드에서는 conversation_log.pop() 등을 사용했지만,
            # 이는 실제 삭제된 메시지와 로그 항목의 동기화를 보장하지 않습니다.
            # conversation_log를 관리하는 더 나은 방법(예: 메시지 ID 기반 관리)으로
            # 리팩토링하기 전까지는 여기서 로그를 직접 수정하는 것은 위험합니다.
            # logger.warning("Conversation log cleanup is currently omitted in GeneralCog.cleanup_messages.")

        except Exception as e:
            logger.error(f"Error during cleanup command: {e}", exc_info=True)
            try:
                await ctx.send("크크… 메시지를 정리하는 중에 문제가 생겼어.", delete_after=10)
            except discord.HTTPException:
                pass # 메시지 전송조차 실패하는 경우

    # --- Event Listeners ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """메시지 수신 시 기본적인 처리 및 로깅"""
        # 봇 자신의 메시지는 무시
        if message.author == self.bot.user:
            return

        # 다른 봇의 메시지도 무시 (선택 사항)
        if message.author.bot:
            return

        # DM 채널이거나, 대상 유저의 메시지일 경우 활동 시간 갱신
        # (봇이 특정 유저하고만 상호작용하는 경우 이 조건 강화 가능)
        if isinstance(message.channel, discord.DMChannel) or self.is_target_user(message.author):
            update_last_active()
            logger.debug(f"Activity time updated by user {message.author} in channel {message.channel.id}")

        # 명령어 처리 전 기본적인 로그 남기기
        # logger.debug(f"Message received: '{message.content}' from {message.author} in {message.channel}")

        # 중요: Cog에서는 process_commands를 자동으로 호출하지 않습니다.
        # Bot 클래스에서 on_message를 오버라이드하지 않는 한, 기본적으로 명령어 처리가 됩니다.
        # 만약 Bot 클래스에서 on_message를 오버라이드하여 여기서 모든 메시지 처리를
        # 하려고 한다면, 마지막에 await self.bot.process_commands(message)를 호출해야 합니다.
        # 현재 구조에서는 Bot 클래스에서 on_message를 오버라이드하지 않을 것이므로 필요 없습니다.

# Cog를 봇에 추가하기 위한 필수 설정 함수
async def setup(bot: commands.Bot):
    await bot.add_cog(GeneralCog(bot))
    logger.info("GeneralCog has been loaded.")
