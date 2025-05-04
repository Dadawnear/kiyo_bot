import discord
from discord.ext import commands
import logging
import re
from typing import Optional, TYPE_CHECKING

import config # 설정 임포트
from utils.helpers import is_target_user # 대상 유저 확인 헬퍼

# 타입 힌트를 위해 KiyoBot 및 Service 클래스 임포트 (순환 참조 방지)
if TYPE_CHECKING:
    from bot.client import KiyoBot
    from services.ai_service import AIService
    from services.notion_service import NotionService
    from services.midjourney_service import MidjourneyService

logger = logging.getLogger(__name__)

class NotionFeaturesCog(commands.Cog, name="Notion"):
    """Notion 데이터베이스 연동 기능 (일기, 관찰, 기억)"""

    # bot 타입을 KiyoBot으로 명시하여 자동완성 및 타입 검사 활용
    def __init__(self, bot: 'KiyoBot'):
        self.bot = bot
        # 서비스 인스턴스 가져오기 (bot 객체에 저장된 것 사용)
        # 이 시점에서 bot 객체에는 서비스들이 초기화되어 있어야 함
        self.ai_service: 'AIService' = bot.ai_service
        self.notion_service: 'NotionService' = bot.notion_service
        self.midjourney_service: 'MidjourneyService' = bot.midjourney_service

    # --- Commands ---
    @commands.command(name='diary', help='현재까지의 대화를 바탕으로 일기를 생성하여 Notion에 기록합니다. (!diary [스타일])')
    async def create_diary_entry(self, ctx: commands.Context, style: Optional[str] = "full_diary"):
        """Notion 일기 생성 명령어"""
        if not is_target_user(ctx.author):
            logger.debug(f"Diary command ignored from non-target user: {ctx.author}")
            return

        channel_id = ctx.channel.id
        # KiyoBot 클래스에 구현된 메소드 사용
        conversation_log = self.bot.get_conversation_log(channel_id)

        if not conversation_log:
            await ctx.send("크크… 아직 나눈 이야기가 없어서 일기를 쓸 수 없네.")
            return

        allowed_styles = ["full_diary", "fragment", "dream_record", "ritual_entry"]
        if style not in allowed_styles:
            await ctx.send(f"크크… '{style}' 스타일은 사용할 수 없어. ({', '.join(allowed_styles)} 중 하나를 선택해줘.)")
            return

        processing_msg = await ctx.send(f"크크… `{style}` 스타일로 일기를 쓰는 중이야. 잠시만 기다려줘...")

        try:
            # 1. AI 서비스로 일기 텍스트 생성
            diary_text = await self.ai_service.generate_diary_entry(conversation_log, style)
            if not diary_text:
                await processing_msg.edit(content="크크… 일기 내용을 생성하지 못했어.")
                return

            # 2. 감정 탐지
            emotion_key = await self.ai_service.detect_emotion(diary_text)

            # 3. Notion 서비스로 업로드 (이미지 없이 먼저 업로드)
            page_id = await self.notion_service.upload_diary_entry(diary_text, emotion_key, style, image_url=None)
            if not page_id:
                await processing_msg.edit(content="크크… 일기를 Notion에 저장하지 못했어.")
                return

            # 4. 마지막 페이지 ID 저장 (KiyoBot 클래스 메소드 사용)
            self.bot.set_last_diary_page_id(channel_id, page_id)

            # 5. Midjourney 프롬프트 생성 및 전송
            mj_info = ""
            try:
                image_prompt = await self.ai_service.generate_image_prompt(diary_text)
                # Midjourney 서비스 호출 (bot 인스턴스 전달)
                await self.midjourney_service.send_midjourney_prompt(self.bot, image_prompt)
                mj_info = "Midjourney 이미지 생성도 요청했어."
                logger.info(f"Requested Midjourney image for diary {page_id}.")
            except Exception as mj_e:
                logger.error(f"Failed to request Midjourney image for diary {page_id}: {mj_e}")
                mj_info = "Midjourney 이미지 생성 요청은 실패했어."

            await processing_msg.edit(content=f"스타일: `{style}` | 감정: `{emotion_key}` — 일기를 남겼어. {mj_info} (ID: {page_id})")
            logger.info(f"Diary entry created (Style: {style}, Emotion: {emotion_key}, PageID: {page_id}) for channel {channel_id}")

            # 일기 생성 후 대화 로그 초기화 (선택적)
            # self.bot.clear_conversation_log(channel_id)
            # logger.info(f"Cleared conversation log for channel {channel_id} after diary creation.")

        except Exception as e:
            logger.error(f"Error creating diary entry for channel {channel_id}: {e}", exc_info=True)
            await processing_msg.edit(content="크크… 일기를 생성하는 중에 오류가 발생했어.")


    @commands.command(name='observe', help='현재까지의 대화를 바탕으로 관찰 기록을 생성하여 Notion에 기록합니다.')
    async def create_observation_log(self, ctx: commands.Context):
        """Notion 관찰 기록 생성 명령어"""
        if not is_target_user(ctx.author):
            logger.debug(f"Observe command ignored from non-target user: {ctx.author}")
            return

        channel_id = ctx.channel.id
        conversation_log = self.bot.get_conversation_log(channel_id)

        if not conversation_log:
            await ctx.send("크크… 아직 나눈 이야기가 없어서 관찰 기록을 쓸 수 없네.")
            return

        processing_msg = await ctx.send("크크… 오늘의 관찰 기록을 정리하는 중이야...")

        try:
            # 1. AI 서비스로 관찰 기록 텍스트 생성 (제목/태그는 AI가 텍스트 내에 포함하도록 프롬프트 구성 가정)
            observation_text = await self.ai_service.generate_observation_log(conversation_log)
            if not observation_text:
                await processing_msg.edit(content="크크… 관찰 기록 내용을 생성하지 못했어.")
                return

            # 2. 관찰 기록 제목 및 태그 생성/추출 (여기서는 임시값 사용, 실제로는 AI가 생성하거나 Notion 서비스가 처리)
            # TODO: AI 서비스 또는 Notion 서비스에서 제목/태그 생성 로직 구현 필요
            current_date_str = datetime.now(config.KST).strftime('%Y-%m-%d')
            title = f"{current_date_str} 관찰 기록" # 임시 제목
            tags = ["관찰"] # 임시 태그

            # 3. Notion 서비스로 업로드
            page_id = await self.notion_service.upload_observation(observation_text, title, tags)
            if page_id:
                 await processing_msg.edit(content="크크… 오늘의 서영 관찰 기록도 정리해뒀어.")
                 logger.info(f"Observation log created (PageID: {page_id}) for channel {channel_id}")
                 # 관찰 기록 생성 후 로그 초기화 (선택적)
                 # self.bot.clear_conversation_log(channel_id)
            else:
                 await processing_msg.edit(content="크크… 관찰 기록을 Notion에 저장하지 못했어.")


        except Exception as e:
            logger.error(f"Error creating observation log for channel {channel_id}: {e}", exc_info=True)
            await processing_msg.edit(content="크크… 관찰 기록을 생성하는 중에 오류가 발생했어.")


    # --- Event Listeners ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """메시지 내용에 '기억해' 등이 포함되어 있으면 Notion 기억 DB에 저장"""
        # 1. 기본 필터링: 봇, 명령어, 대상유저/DM 아니면 무시
        if message.author.bot or not is_target_user(message.author):
            return
        if not isinstance(message.channel, discord.DMChannel): # DM 채널만 처리 가정
             return
        ctx = await self.bot.get_context(message)
        if ctx.valid: # 명령어도 무시
            return

        # 2. 기억 관련 키워드 확인
        keywords = ["기억해", "기억해줘", "잊지 마", "기억할래", "기억 좀"]
        if any(keyword in message.content for keyword in keywords):
            logger.info(f"Memory keyword detected in message: {message.id} from {message.author}")

            try:
                # 3. AI 서비스로 요약 생성
                summary = await self.ai_service.generate_memory_summary(message.content)
                if not summary:
                     logger.warning(f"Failed to generate memory summary for message {message.id}.")
                     # 실패 시 사용자에게 알릴 수도 있음
                     return

                # 4. Notion 서비스로 업로드
                page_id = await self.notion_service.upload_memory(
                    original_text=message.content,
                    summary=summary,
                    message_url=message.jump_url # 메시지 링크 포함
                    # tags=[], category="일반", status="기억 중" # 필요시 추가 정보 전달
                )

                if page_id:
                    # 5. 사용자에게 피드백
                    await message.reply("크크… 네 말, 기억해둘게.", mention_author=False)
                    logger.info(f"Memory saved to Notion (PageID: {page_id}) for message: {message.id}")
                    # 중요: 이 메시지는 처리되었으므로, GeneralCog의 on_message에서
                    # 추가적인 AI 응답 생성을 막아야 함.
                    # 이를 위한 플래그 설정 또는 처리 로직 필요.
                    # 예: message 객체에 handled 플래그 추가 (message.handled = True)? -> 비표준적
                    # 예: bot 객체에 최근 처리된 메시지 ID 저장?
                    # 여기서는 일단 로그만 남기고, GeneralCog 수정 필요 가능성 인지.
                    logger.debug(f"Memory listener handled message {message.id}. GeneralCog response might need prevention.")
                else:
                    await message.reply("크크… 기억하려고 했는데, Notion 저장에 실패했어.", mention_author=False)

            except Exception as e:
                logger.error(f"Error saving memory for message {message.id}: {e}", exc_info=True)
                try:
                    await message.reply("크크… 기억 저장 중 오류가 발생했어.", mention_author=False)
                except discord.HTTPException:
                    pass


# Cog를 봇에 추가하기 위한 필수 설정 함수
async def setup(bot: 'KiyoBot'):
    await bot.add_cog(NotionFeaturesCog(bot))
    logger.info("NotionFeaturesCog has been loaded.")
