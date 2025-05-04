import discord
from discord.ext import commands
import logging
import re
from typing import Optional

import config

# --- Service Imports (실제 서비스 모듈 생성 후 경로 확정) ---
# 이 부분은 services/ 디렉토리에 해당 파일들이 구현된 후 주석 해제 및 수정 필요
# from services.ai_service import AIService
# from services.notion_service import NotionService
# from services.midjourney_service import MidjourneyService

# --- 임시 Service Placeholder (실제 구현 전 테스트용) ---
# 실제 서비스 구현 전까지는 아래 클래스를 임시로 사용하거나,
# Bot 객체에 서비스 인스턴스를 주입한다고 가정하고 진행합니다.
class PlaceholderAIService:
    async def generate_diary_entry(self, log, style): return f"Generated diary (style: {style})"
    async def detect_emotion(self, text): return "기록"
    async def generate_image_prompt(self, text): return f"Image prompt for: {text[:50]}..."
    async def generate_observation_log(self, log): return "Generated observation log."
    async def generate_memory_summary(self, text): return f"Summary: {text[:30]}..."

class PlaceholderNotionService:
    async def upload_diary_entry(self, text, emotion, style, image_url=None): return "dummy_page_id_123"
    async def upload_observation(self, text, title, tags): pass
    async def upload_memory(self, original_text, summary, message_url=None, tags=None, category=None, status=None): pass
    async def generate_observation_title(self, text): return "Observation Title Placeholder" # 임시 추가
    async def generate_observation_tags(self, text): return ["기록", "분석"] # 임시 추가

class PlaceholderMidjourneyService:
    async def send_midjourney_prompt(self, bot_instance, prompt): logger.info(f"MJ Prompt Sent (Placeholder): {prompt}")

# --- Logger ---
logger = logging.getLogger(__name__)

class NotionFeaturesCog(commands.Cog, name="Notion"):
    """Notion 데이터베이스 연동 기능 (일기, 관찰, 기억)"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # --- 서비스 인스턴스 주입 (Bot 객체에 서비스가 추가되었다고 가정) ---
        # 실제로는 bot/client.py에서 서비스들을 초기화하고 self.bot에 할당해야 함
        # self.ai_service: AIService = bot.ai_service
        # self.notion_service: NotionService = bot.notion_service
        # self.midjourney_service: MidjourneyService = bot.midjourney_service

        # --- 임시 Placeholder 사용 ---
        self.ai_service = PlaceholderAIService()
        self.notion_service = PlaceholderNotionService()
        self.midjourney_service = PlaceholderMidjourneyService()

        # --- 상태 관리 (Bot 객체에 위임 가정) ---
        # 예: self.bot.conversation_logs = {}
        # 예: self.bot.last_diary_page_ids = {}
        # 초기화 확인
        if not hasattr(bot, 'conversation_logs'):
            bot.conversation_logs = {} # 채널 ID를 키로 사용
            logger.info("Initialized conversation_logs attribute on bot.")
        if not hasattr(bot, 'last_diary_page_ids'):
            bot.last_diary_page_ids = {} # 채널 ID를 키로 사용
            logger.info("Initialized last_diary_page_ids attribute on bot.")


    # --- Helper Functions ---
    def is_target_user(self, author: discord.User | discord.Member) -> bool:
        """명령어나 메시지 발신자가 설정된 대상 유저인지 확인"""
        # GeneralCog에도 동일한 함수가 있으므로, utils/helpers.py로 옮기는 것이 좋음
        if config.TARGET_USER_ID:
            return author.id == config.TARGET_USER_ID
        elif config.TARGET_USER_DISCORD_NAME:
            return str(author) == config.TARGET_USER_DISCORD_NAME
        else:
            return True # 타겟 유저 설정 없으면 일단 허용

    def get_conversation_log(self, channel_id: int) -> list:
        """채널 ID에 해당하는 대화 기록 가져오기 (Bot 객체에서 관리 가정)"""
        return self.bot.conversation_logs.get(channel_id, [])

    def set_last_diary_page_id(self, channel_id: int, page_id: str):
        """마지막으로 생성된 일기 페이지 ID 저장 (Bot 객체에서 관리 가정)"""
        self.bot.last_diary_page_ids[channel_id] = page_id
        logger.debug(f"Stored last diary page ID for channel {channel_id}: {page_id}")

    # --- Commands ---
    @commands.command(name='diary', help='현재까지의 대화를 바탕으로 일기를 생성하여 Notion에 기록합니다. (!diary [스타일])')
    async def create_diary_entry(self, ctx: commands.Context, style: Optional[str] = "full_diary"):
        """Notion 일기 생성 명령어"""
        if not self.is_target_user(ctx.author):
            logger.debug(f"Diary command ignored from non-target user: {ctx.author}")
            return

        channel_id = ctx.channel.id
        conversation_log = self.get_conversation_log(channel_id)

        if not conversation_log:
            await ctx.send("크크… 아직 나눈 이야기가 없어서 일기를 쓸 수 없네.")
            return

        # 유효한 스타일인지 확인 (선택적)
        allowed_styles = ["full_diary", "fragment", "dream_record", "ritual_entry"]
        if style not in allowed_styles:
            await ctx.send(f"크크… '{style}' 스타일은 사용할 수 없어. ({', '.join(allowed_styles)} 중 하나를 선택해줘.)")
            return

        processing_msg = await ctx.send(f"크크… `{style}` 스타일로 일기를 쓰는 중이야. 잠시만 기다려줘...")

        try:
            # 1. AI 서비스로 일기 텍스트 생성
            # generate_diary_entry는 대화 기록(log)과 스타일(style)을 인자로 받음
            diary_text = await self.ai_service.generate_diary_entry(conversation_log, style)
            if not diary_text:
                await processing_msg.edit(content="크크… 일기 내용을 생성하지 못했어.")
                return

            # 2. 감정 탐지
            emotion_key = await self.ai_service.detect_emotion(diary_text)

            # 3. Notion에 업로드 (이미지 없이 먼저 업로드)
            # upload_diary_entry는 텍스트, 감정키, 스타일, 이미지 URL(None) 등을 인자로 받음
            page_id = await self.notion_service.upload_diary_entry(diary_text, emotion_key, style, image_url=None)
            if not page_id:
                await processing_msg.edit(content="크크… 일기를 Notion에 저장하지 못했어.")
                return

            # 4. 마지막 페이지 ID 저장 (Midjourney Cog에서 사용)
            self.set_last_diary_page_id(channel_id, page_id)

            # 5. Midjourney 프롬프트 생성 및 전송 (옵션: 생성 실패해도 계속 진행)
            try:
                image_prompt = await self.ai_service.generate_image_prompt(diary_text)
                await self.midjourney_service.send_midjourney_prompt(self.bot, image_prompt)
                mj_info = "Midjourney 이미지 생성도 요청했어."
            except Exception as mj_e:
                logger.error(f"Failed to request Midjourney image: {mj_e}")
                mj_info = "Midjourney 이미지 생성 요청은 실패했어."

            await processing_msg.edit(content=f"스타일: `{style}` | 감정: `{emotion_key}` — 일기를 남겼어. {mj_info} (ID: {page_id})")
            logger.info(f"Diary entry created (Style: {style}, Emotion: {emotion_key}, PageID: {page_id}) for channel {channel_id}")

        except Exception as e:
            logger.error(f"Error creating diary entry: {e}", exc_info=True)
            await processing_msg.edit(content="크크… 일기를 생성하는 중에 오류가 발생했어.")


    @commands.command(name='observe', help='현재까지의 대화를 바탕으로 관찰 기록을 생성하여 Notion에 기록합니다.')
    async def create_observation_log(self, ctx: commands.Context):
        """Notion 관찰 기록 생성 명령어"""
        if not self.is_target_user(ctx.author):
            logger.debug(f"Observe command ignored from non-target user: {ctx.author}")
            return

        channel_id = ctx.channel.id
        conversation_log = self.get_conversation_log(channel_id)

        if not conversation_log:
            await ctx.send("크크… 아직 나눈 이야기가 없어서 관찰 기록을 쓸 수 없네.")
            return

        processing_msg = await ctx.send("크크… 오늘의 관찰 기록을 정리하는 중이야...")

        try:
            # 1. AI 서비스로 관찰 기록 텍스트 생성
            observation_text = await self.ai_service.generate_observation_log(conversation_log)
            if not observation_text:
                await processing_msg.edit(content="크크… 관찰 기록 내용을 생성하지 못했어.")
                return

            # 2. 관찰 기록 제목 및 태그 생성 (Notion 서비스 내부에 구현될 수도 있음)
            # 이 예시에서는 Notion 서비스가 담당한다고 가정
            title = await self.notion_service.generate_observation_title(observation_text)
            tags = await self.notion_service.generate_observation_tags(observation_text)


            # 3. Notion에 업로드
            # upload_observation은 텍스트, 제목, 태그 등을 인자로 받음
            await self.notion_service.upload_observation(observation_text, title, tags)

            await processing_msg.edit(content="크크… 오늘의 서영 관찰 기록도 정리해뒀어.")
            logger.info(f"Observation log created for channel {channel_id}")

        except Exception as e:
            logger.error(f"Error creating observation log: {e}", exc_info=True)
            await processing_msg.edit(content="크크… 관찰 기록을 생성하는 중에 오류가 발생했어.")


    # --- Event Listeners ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """메시지 내용에 '기억해' 등이 포함되어 있으면 Notion 기억 DB에 저장"""
        # 봇 메시지, 명령어, 타겟 유저 아닌 경우 등 기본 필터링은 GeneralCog 등에서 처리했다고 가정
        # 또는 여기서 추가 필터링 수행
        if message.author.bot or not self.is_target_user(message.author):
            return

        # 명령어 형식 메시지는 무시 (예: !)
        if message.content.startswith(config.BOT_PREFIX):
            return

        # 기억 관련 키워드 확인
        keywords = ["기억해", "기억해줘", "잊지 마", "기억할래", "기억 좀"]
        if any(keyword in message.content for keyword in keywords):
            logger.info(f"Memory keyword detected in message: {message.id}")
            # 여기서 바로 처리하거나, 혹은 '처리 중' 반응 후 background task로 넘길 수도 있음

            try:
                # 1. AI 서비스로 요약 생성
                summary = await self.ai_service.generate_memory_summary(message.content)

                # 2. Notion에 업로드
                await self.notion_service.upload_memory(
                    original_text=message.content,
                    summary=summary,
                    message_url=message.jump_url # 메시지 링크 추가
                    # tags=[], # 필요시 태그 추가 로직 구현
                    # category="일반", # 필요시 카테고리 추가 로직 구현
                    # status="기억 중" # 필요시 상태 추가 로직 구현
                )

                # 사용자에게 피드백 (리액션 또는 답장)
                await message.reply("크크… 네 말, 기억해둘게.", mention_author=False)
                logger.info(f"Memory saved to Notion for message: {message.id}")

                # 중요: 기억 저장이 완료되었으므로, 이 메시지에 대해
                # 일반적인 Kiyo 응답 생성(다른 Cog나 리스너에서 처리될 수 있음)을
                # 방지해야 할 수 있습니다. (예: 특정 플래그 설정 또는 여기서 return)
                # 현재 구조에서는 이 리스너가 다른 on_message 리스너보다 먼저 실행된다는 보장이 없으므로,
                # on_message 처리 순서나 방식에 대한 고민이 필요합니다.

            except Exception as e:
                logger.error(f"Error saving memory for message {message.id}: {e}", exc_info=True)
                try:
                    await message.reply("크크… 기억하려고 했는데, 오류가 발생했어.", mention_author=False)
                except discord.HTTPException:
                    pass # 답장조차 실패하는 경우


# Cog를 봇에 추가하기 위한 필수 설정 함수
async def setup(bot: commands.Bot):
    await bot.add_cog(NotionFeaturesCog(bot))
    logger.info("NotionFeaturesCog has been loaded.")
