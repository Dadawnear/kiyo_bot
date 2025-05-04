import discord
from discord.ext import commands # commands.Bot 타입을 명시하기 위해 사용
import logging

import config # 설정 임포트

logger = logging.getLogger(__name__)

class MidjourneyServiceError(Exception):
    """Midjourney 서비스 관련 커스텀 오류"""
    pass

class MidjourneyService:
    """
    Midjourney 봇과의 상호작용 (프롬프트 전송)을 담당하는 서비스 클래스.
    """

    def __init__(self):
        # 초기화 시점에 특별히 설정할 내용은 없을 수 있음
        # 필요하다면 API 키나 다른 설정을 여기서 로드
        if not all([config.MIDJOURNEY_BOT_ID, config.MIDJOURNEY_SERVER_NAME, config.MIDJOURNEY_CHANNEL_NAME]):
            logger.warning("Midjourney 관련 설정(BOT_ID, SERVER_NAME, CHANNEL_NAME) 중 일부가 누락되었습니다. 기능이 제한될 수 있습니다.")

    async def send_midjourney_prompt(self, bot: commands.Bot, prompt_text: str):
        """
        설정된 서버/채널을 찾아 Midjourney 봇에게 '/imagine' 프롬프트를 전송합니다.

        Args:
            bot: 현재 실행 중인 discord.ext.commands.Bot 인스턴스.
            prompt_text: Midjourney에 전달할 프롬프트 텍스트 (스타일 접미사 등은 자동으로 추가됨).

        Raises:
            MidjourneyServiceError: 서버/채널을 찾지 못하거나 메시지 전송에 실패한 경우.
        """
        if not all([config.MIDJOURNEY_BOT_ID, config.MIDJOURNEY_SERVER_NAME, config.MIDJOURNEY_CHANNEL_NAME]):
            raise MidjourneyServiceError("Midjourney 관련 설정(BOT_ID, SERVER_NAME, CHANNEL_NAME)이 누락되어 프롬프트를 전송할 수 없습니다.")

        # 1. 대상 서버 찾기
        target_guild = discord.utils.get(bot.guilds, name=config.MIDJOURNEY_SERVER_NAME)
        if not target_guild:
            logger.error(f"Midjourney 서버 '{config.MIDJOURNEY_SERVER_NAME}'를 찾을 수 없습니다.")
            raise MidjourneyServiceError(f"Midjourney 서버 '{config.MIDJOURNEY_SERVER_NAME}'를 찾을 수 없습니다.")

        # 2. 대상 채널 찾기
        # 채널 ID를 직접 사용하는 것이 더 안정적일 수 있음 (설정에 CHANNEL_ID 추가)
        target_channel = discord.utils.get(target_guild.text_channels, name=config.MIDJOURNEY_CHANNEL_NAME)
        if not target_channel:
            logger.error(f"Midjourney 채널 '{config.MIDJOURNEY_CHANNEL_NAME}'를 서버 '{target_guild.name}'에서 찾을 수 없습니다.")
            raise MidjourneyServiceError(f"Midjourney 채널 '{config.MIDJOURNEY_CHANNEL_NAME}'를 서버 '{target_guild.name}'에서 찾을 수 없습니다.")

        # 3. 최종 프롬프트 구성 (mention + imagine command + style + user prompt + aspect ratio)
        # 스타일 접미사와 종횡비는 config에서 관리
        final_prompt = (
            f"<@{config.MIDJOURNEY_BOT_ID}> imagine prompt: "
            f"{config.MIDJOURNEY_STYLE_SUFFIX}, {prompt_text} "
            f"{config.MIDJOURNEY_DEFAULT_AR}"
        )

        logger.debug(f"Attempting to send Midjourney prompt to #{target_channel.name} in {target_guild.name}: {final_prompt}")

        # 4. 메시지 전송
        try:
            await target_channel.send(final_prompt)
            logger.info(f"Successfully sent Midjourney prompt to #{target_channel.name}: {prompt_text[:100]}...")
        except discord.Forbidden:
            logger.error(f"봇이 '{target_channel.name}' 채널에 메시지를 보낼 권한이 없습니다.")
            raise MidjourneyServiceError(f"봇이 '{target_channel.name}' 채널에 메시지를 보낼 권한이 없습니다.")
        except discord.HTTPException as e:
            logger.error(f"Midjourney 프롬프트 전송 중 Discord API 오류 발생: {e}")
            raise MidjourneyServiceError(f"Midjourney 프롬프트 전송 중 Discord API 오류 발생: {e.status}")
        except Exception as e:
            logger.error(f"Midjourney 프롬프트 전송 중 예상치 못한 오류 발생: {e}", exc_info=True)
            raise MidjourneyServiceError(f"Midjourney 프롬프트 전송 중 예상치 못한 오류 발생.")


# MidjourneyService 인스턴스 생성 (싱글턴처럼 사용 가능)
# midjourney_service_instance = MidjourneyService()

# 다른 모듈에서 사용 예시:
# from .midjourney_service import midjourney_service_instance
# await midjourney_service_instance.send_midjourney_prompt(bot_instance, "a cat dreaming")
