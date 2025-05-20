import discord
from discord.ext import commands
import logging
from typing import Literal, Optional, TYPE_CHECKING, get_args # get_args 추가

import config # 설정 임포트
from utils.helpers import is_target_user # 대상 유저 확인 _헬퍼

# 타입 힌트를 위해 KiyoBot 클래스 임포트 (순환 참조 방지)
if TYPE_CHECKING:
    from bot.client import KiyoBot

logger = logging.getLogger(__name__)

# 사용자가 지정한 사용 가능한 무드 정의
AVAILABLE_MOODS = Literal["기본", "장난", "진지"]
AVAILABLE_KIYO_EMOTIONS = Literal[
    "고요함", "흥미", "냉소", "불쾌함", "탐구심", "미묘한 슬픔"
]

class MoodCog(commands.Cog, name="Mood and Emotion Management"):
    """봇의 대화 무드를 관리하는 명령어들을 포함합니다."""

    def __init__(self, bot: 'KiyoBot'):
        self.bot = bot
        self.ai_service: 'AIService' = bot.ai_service

    @commands.command(name="무드", help="봇의 대화 무드를 변경합니다. (사용 가능: 기본, 장난, 진지)")
    async def set_mood(self, ctx: commands.Context, new_mood: AVAILABLE_MOODS):
        """봇의 대화 무드를 설정합니다. 예: !무드 장난"""
        if not is_target_user(ctx.author):
            # 대상 유저가 아니면 조용히 무시하거나 권한 없음을 알릴 수 있음
            logger.debug(f"Mood command ignored from non-target user: {ctx.author}")
            return

        # KiyoBot 클래스에 정의된 메소드 호출
        self.bot.set_conversation_mood(new_mood)
        await ctx.send(f"크크… 나의 대화 무드를 '{new_mood}'(으)로 변경했어.")
        logger.info(f"Conversation mood changed to '{new_mood}' by {ctx.author.name}.")

    @set_mood.error
    async def set_mood_error(self, ctx: commands.Context, error: commands.CommandError):
        """!무드 명령어 오류 처리기"""
        if isinstance(error, commands.BadArgument):
            mood_options = get_args(AVAILABLE_MOODS)
            await ctx.send(f"크크… 그런 무드는 잘 모르겠네. '{', '.join(mood_options)}' 중에서 골라줄 수 있을까?")
        else:
            # 다른 일반적인 명령어 오류는 KiyoBot의 on_command_error에서 처리될 수 있음
            logger.error(f"Error in set_mood command: {error}", exc_info=True)
            await ctx.send("크크… 무드를 변경하는 중에 문제가 생긴 것 같아.")


    @commands.command(name="현재무드", help="봇의 현재 대화 무드를 확인합니다.")
    async def check_mood(self, ctx: commands.Context):
        """봇의 현재 대화 무드를 확인합니다."""
        if not is_target_user(ctx.author):
            logger.debug(f"Check_mood command ignored from non-target user: {ctx.author}")
            return

        # KiyoBot 클래스에 정의된 메소드 호출
        current_mood = self.bot.get_conversation_mood()
        await ctx.send(f"크크… 현재 나의 대화 무드는 '{current_mood}'(으)로 설정되어 있지.")
        logger.info(f"Current mood '{current_mood}' checked by {ctx.author.name}.")

    @commands.command(name="무드목록", help="사용 가능한 대화 무드 목록을 보여줍니다.")
    async def list_moods(self, ctx: commands.Context):
        """사용 가능한 대화 무드 목록을 보여줍니다."""
        if not is_target_user(ctx.author):
            logger.debug(f"List_moods command ignored from non-target user: {ctx.author}")
            return

        # AVAILABLE_MOODS Literal에서 실제 값들을 가져옴
        mood_options = get_args(AVAILABLE_MOODS)
        mood_list_str = ", ".join(mood_options)
        await ctx.send(f"크크… 내가 이해할 수 있는 무드는 다음과 같아: {mood_list_str}.")
        logger.info(f"Available moods list requested by {ctx.author.name}.")

    # --- <<< 새로운 명령어: 키요의 현재 감정 확인 >>> ---
    @commands.command(name="키요감정", aliases=["현재감정", "기분"], help="키요의 현재 내면 감정 상태를 알려줍니다.")
    async def get_kiyo_internal_emotion(self, ctx: commands.Context):
        """키요의 현재 내면 감정 상태를 AI가 생성한 텍스트로 알려줍니다."""
        if not is_target_user(ctx.author):
            logger.debug(f"Kiyo_emotion command ignored from non-target user: {ctx.author}")
            return

        current_kiyo_emotion = self.bot.get_kiyo_emotion()
        current_conversation_mood = self.bot.get_conversation_mood() # 감정 표현 시 현재 무드도 고려

        # AI 서비스를 호출하여 키요의 말투로 감정 상태 설명 생성
        try:
            processing_msg = await ctx.send("크크… 지금 나의 감정이라… 잠시 생각 좀 해볼게…")
            emotion_statement = await self.ai_service.generate_self_emotion_statement(
                kiyo_emotion=current_kiyo_emotion,
                current_mood=current_conversation_mood
            )
            await processing_msg.edit(content=emotion_statement)
            logger.info(f"Provided Kiyo's current emotion '{current_kiyo_emotion}' statement to {ctx.author.name}.")
        except Exception as e:
            logger.error(f"Error generating Kiyo's emotion statement: {e}", exc_info=True)
            await ctx.send(f"크크… 지금은 내 감정을 표현하기가 조금… 어렵네. 현재 상태는 '{current_kiyo_emotion}'인 것 같지만.")


# Cog를 봇에 추가하기 위한 필수 설정 함수
async def setup(bot: 'KiyoBot'):
    await bot.add_cog(MoodCog(bot))
    logger.info("MoodCog has been loaded.")
