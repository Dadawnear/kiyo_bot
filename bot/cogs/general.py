import discord
from discord.ext import commands
import logging
import re
from typing import TYPE_CHECKING, Optional, List, Tuple, Dict 
from datetime import datetime, time, timedelta
import config # 설정 임포트
from utils.activity_tracker import update_last_active # 유틸리티 임포트
from utils.helpers import is_target_user # 헬퍼 함수 임포트

# 타입 힌트를 위해 KiyoBot 클래스 임포트 (순환 참조 방지)
if TYPE_CHECKING:
    from bot.client import KiyoBot

logger = logging.getLogger(__name__)

class GeneralCog(commands.Cog):
    """봇의 일반적인 기능 및 핵심 메시지 처리 로직 담당"""

    # bot 타입을 KiyoBot으로 명시하여 자동완성 및 타입 검사 활용
    def __init__(self, bot: 'KiyoBot'):
        self.bot = bot

    # --- Commands ---
    @commands.command(name='cleanup', help='봇이 최근에 보낸 메시지를 지정한 개수만큼 삭제하고, 관련 대화 기록도 일부 제거합니다.')
    async def cleanup_messages(self, ctx: commands.Context, limit: int = 1):
        """봇의 최근 메시지를 삭제하고 관련 대화 기록 일부를 제거하는 명령어"""
        if not is_target_user(ctx.author):
            logger.debug(f"Cleanup command ignored from non-target user: {ctx.author}")
            return

        if limit <= 0:
            await ctx.send("크크… 1 이상의 숫자를 알려줘야 해.", delete_after=10)
            return
        if limit > 25: # 한 번에 너무 많이 지우는 것 방지 (기존 50에서 줄임)
             await ctx.send("크크… 한 번에 너무 많이 지우려는 것 같아. 25개 이하로 해줘.", delete_after=10)
             return

        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound) as e:
            logger.warning(f"Could not delete command message: {e}")

        deleted_count = 0
        try:
            # 채널 기록 확인 및 봇 메시지 삭제
            # limit * 5 보다 좀 더 보수적으로 가져와서 봇 메시지만 카운트
            async for message in ctx.channel.history(limit=limit * 10):
                if message.author == self.bot.user:
                    try:
                        await message.delete()
                        deleted_count += 1
                        if deleted_count >= limit:
                            break
                    except (discord.Forbidden, discord.NotFound) as e:
                         logger.warning(f"Could not delete bot message {message.id}: {e}")
                    except discord.HTTPException as e:
                        logger.error(f"Failed to delete message {message.id} due to HTTP error: {e}")
                        # API 오류 시 잠시 대기 후 다음 메시지 시도 또는 중단 결정 가능
                        await asyncio.sleep(1) # 간단히 1초 대기

            await ctx.send(f"크크… 내 메시지 {deleted_count}개를 정리했어.", delete_after=5)
            logger.info(f"Cleaned up {deleted_count} bot messages in channel {ctx.channel.id} by {ctx.author}")

            # --- conversation_log 수정 로직 추가 ---
            if deleted_count > 0:
                channel_id = ctx.channel.id
                # KiyoBot 클래스에 구현된 get_conversation_log 사용
                log = self.bot.get_conversation_log(channel_id)
                if log: # 로그가 있는 경우에만 처리
                    # 삭제된 봇 메시지 수의 2배만큼 최근 로그 항목 제거 (사용자-봇 쌍으로 가정)
                    # (주의: 이 방식은 완벽하지 않으며, 상황에 따라 정확하지 않을 수 있음)
                    entries_to_remove_from_log = min(len(log), deleted_count * 2)

                    if entries_to_remove_from_log > 0:
                        # KiyoBot 클래스의 conversation_logs를 직접 수정
                        self.bot.conversation_logs[channel_id] = log[:-entries_to_remove_from_log]
                        logger.info(f"Removed last {entries_to_remove_from_log} entries from conversation log for channel {channel_id} due to cleanup.")
                else:
                    logger.info(f"Conversation log for channel {channel_id} is empty. No log entries removed.")

        except Exception as e:
            logger.error(f"Error during cleanup command processing: {e}", exc_info=True)
            try:
                await ctx.send("크크… 메시지를 정리하는 중에 오류가 생겼어.", delete_after=10)
            except discord.HTTPException:
                pass

    # --- Event Listeners ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        메시지 수신 시 처리: 필터링, 활동 기록, 키요 감정 결정, 대화 로그 추가, AI 응답 생성/전송.
        명령어, 다른 Cog에서 처리한 메시지는 응답 생성 안 함.
        """
        # 1. 기본 필터링: 봇 자신, 다른 봇 메시지 무시
        if message.author == self.bot.user or message.author.bot:
            return

        # 2. 명령어 형식 메시지 무시 (명령어 처리는 Bot 객체가 알아서 함)
        ctx = await self.bot.get_context(message)
        if ctx.valid: # 메시지가 유효한 명령어 형식이면 여기서 처리 중단
            logger.debug(f"Ignoring message as it's a valid command: {message.content}")
            return

        # 3. 대상 유저 및 DM 채널 필터링 (봇 설정에 따라 조절)
        # 여기서는 대상 유저이거나 DM 채널인 경우만 처리하도록 가정
        is_dm = isinstance(message.channel, discord.DMChannel)
        target_user = is_target_user(message.author)

        if not (is_dm and target_user): # 대상 유저의 DM이 아니면 무시
             # logger.debug(f"Ignoring message from non-target user/channel: User={message.author}, Channel={message.channel}")
             return

        # --- 대상 유저의 DM 메시지 처리 ---
        channel_id = message.channel.id
        user_name = message.author.name # 또는 str(message.author)

        # 4. 활동 시간 갱신
        self.bot.update_last_interaction_time()
        update_last_active()
        logger.debug(f"Activity time updated by {user_name}")
        
        # 무드 명령어 가져오기
        current_mood = self.bot.get_conversation_mood()

        # 5. 사용자 메시지 기반으로 키요의 감정 결정
        user_emotion_for_kiyo_reaction = await self.bot.ai_service.detect_emotion(message.content)
        current_conversation_mood = self.bot.get_conversation_mood() # 현재 설정된 대화 무드
        current_kiyo_emotion_before_update = self.bot.get_kiyo_emotion() # 업데이트 전 현재 키요 감정
        # AI 서비스를 호출하여 키요의 다음 감정 결정
        new_kiyo_emotion = await self.bot.ai_service.determine_kiyo_next_emotion(
            conversation_log=self.bot.get_conversation_log(channel_id)[-3:], # 최근 3개 대화 로그 전달
            last_user_message=message.content,
            detected_user_emotion=user_emotion_for_kiyo_reaction,
            current_conversation_mood=current_conversation_mood,
            current_kiyo_emotion=current_kiyo_emotion_before_update
        )
        self.bot.set_kiyo_emotion(new_kiyo_emotion) # 키요 감정 업데이트
        # 로그 메시지에서 이전 감정과 새 감정을 함께 보여주면 변화를 추적하기 좋음
        logger.info(f"[GeneralCog] Kiyo's emotion changed from '{current_kiyo_emotion_before_update}' to '{new_kiyo_emotion}' based on AI determination (User emotion: '{user_emotion_for_kiyo_reaction}', Mood: '{current_conversation_mood}').")

        # 6. 사용자 메시지 대화 로그에 추가
        # add_conversation_log 메소드는 KiyoBot 클래스에 구현됨
        self.bot.add_conversation_log(channel_id, user_name, message.content)
        logger.info(f"Logged message from {user_name} in channel {channel_id}.")

         # 7. AI 응답 생성 및 전송
        try:
            conversation_log_for_response = self.bot.get_conversation_log(channel_id) # 전체 로그 전달
            recent_memories = await self.bot.notion_service.fetch_recent_memories(limit=3)
            recent_observations = await self.bot.notion_service.fetch_recent_observations(limit=1)
            recent_diary_summary = await self.bot.notion_service.fetch_recent_diary_summary(limit=1)

            # 현재 설정된 대화 무드와 AI가 방금 결정한 키요의 감정 상태를 가져와 전달
            final_mood_for_response = self.bot.get_conversation_mood() # 변경 없을 수 있으나, 명시적 호출
            final_kiyo_emotion_for_response = self.bot.get_kiyo_emotion() # AI가 결정한 새 감정

            logger.debug(f"Requesting AI response for channel {channel_id} with mood: '{final_mood_for_response}', kiyo_emotion: '{final_kiyo_emotion_for_response}'")
            kiyo_response = await self.bot.ai_service.generate_response(
                conversation_log=conversation_log_for_response,
                current_mood=final_mood_for_response,
                kiyo_current_emotion=final_kiyo_emotion_for_response,
                recent_memories=recent_memories if isinstance(recent_memories, list) else None,
                recent_observations=recent_observations if isinstance(recent_observations, str) else None,
                recent_diary_summary=recent_diary_summary if isinstance(recent_diary_summary, str) else None
            )

            if kiyo_response:
                await message.channel.send(kiyo_response)
                self.bot.add_conversation_log(channel_id, "キヨ", kiyo_response) # 봇 응답 로그
                logger.info(f"Sent AI response to channel {channel_id}.")
            else:
                logger.warning(f"AI service returned empty response for channel {channel_id}.")

        except Exception as e:
            logger.error(f"Error generating or sending AI response for channel {channel_id}: {e}", exc_info=True)
            try:
                await message.channel.send("크크… 지금은 답하기 어렵네. 무슨 문제가 있는 것 같아.")
            except discord.HTTPException:
                pass


# Cog를 봇에 추가하기 위한 필수 설정 함수
async def setup(bot: commands.Bot):
    # KiyoBot 타입으로 명시적 캐스팅 (선택적)
    await bot.add_cog(GeneralCog(bot)) # type: ignore
    logger.info("GeneralCog has been loaded.")
