import discord
from discord.ext import commands
import logging
import re
from typing import Optional, TYPE_CHECKING

import config # 설정 임포트

# --- Service Imports ---
# 실제 NotionService 임포트
from services.notion_service import NotionService

# 타입 힌트를 위해 KiyoBot 클래스 임포트 (순환 참조 방지)
if TYPE_CHECKING:
    from bot.client import KiyoBot

logger = logging.getLogger(__name__)

class MidjourneyCog(commands.Cog, name="Midjourney Listener"):
    """Midjourney 봇 메시지를 감지하고 Notion 일기와 연동"""

    # bot 타입을 KiyoBot으로 명시
    def __init__(self, bot: 'KiyoBot'):
        self.bot = bot
        # 서비스 인스턴스 가져오기 (bot 객체에 저장된 것 사용)
        self.notion_service: NotionService = bot.notion_service

    # --- Helper Functions ---
    def get_target_guild(self) -> Optional[discord.Guild]:
        """설정된 서버 이름으로 Guild 객체를 찾습니다."""
        if not config.MIDJOURNEY_SERVER_NAME:
            return None
        # 봇이 속한 모든 길드에서 이름으로 검색
        return discord.utils.get(self.bot.guilds, name=config.MIDJOURNEY_SERVER_NAME)

    def get_target_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        """설정된 채널 이름으로 TextChannel 객체를 찾습니다."""
        if not guild or not config.MIDJOURNEY_CHANNEL_NAME:
            return None
        # 길드 내 모든 텍스트 채널에서 이름으로 검색
        return discord.utils.get(guild.text_channels, name=config.MIDJOURNEY_CHANNEL_NAME)

    def get_latest_diary_page_id_from_bot(self) -> Optional[str]:
        """봇 객체에 저장된 마지막 일기 페이지 ID 중 가장 최신 것을 반환"""
        # KiyoBot 클래스에 구현된 메소드 사용
        return self.bot.get_overall_latest_diary_page_id()

    def extract_image_url(self, message: discord.Message) -> Optional[str]:
        """메시지 첨부파일 또는 임베드에서 이미지 URL 추출"""
        # 1. 첨부파일 확인
        if message.attachments:
            for attachment in message.attachments:
                # 이미지 파일 확장자 확인
                if attachment.content_type and attachment.content_type.startswith("image/"):
                     # CDN URL 등 고려하여 쿼리 스트링 제거는 선택적
                     # url_without_query = attachment.url.split("?")[0]
                     logger.debug(f"Image URL extracted from attachment: {attachment.url}")
                     return attachment.url
        # 2. 첨부파일 없으면 임베드 확인
        if message.embeds:
            for embed in message.embeds:
                # 임베드의 image 필드 확인
                if embed.image and embed.image.url:
                    logger.debug(f"Image URL extracted from embed image: {embed.image.url}")
                    return embed.image.url
                # 썸네일은 보통 저화질이므로 제외 (필요시 추가)
        logger.debug(f"No suitable image URL found in message {message.id}")
        return None

    def is_upscaled_image_message(self, message: discord.Message) -> bool:
        """메시지가 업스케일된 최종 이미지 결과인지 추정"""
        # 1. 첨부 파일에 이미지가 있는가?
        has_image_attachment = False
        if message.attachments:
            for attachment in message.attachments:
                 if attachment.content_type and attachment.content_type.startswith("image/"):
                     has_image_attachment = True
                     break
        if not has_image_attachment:
            return False # 이미지 첨부 없으면 최종 결과 아님

        # 2. 메시지 내용 패턴 확인 (옵션 - MJ UI 변경에 따라 불안정할 수 있음)
        content = message.content.lower()
        # 예: " - Upscaled by" 또는 "**prompt** - <@" 같은 패턴
        # if " - upscaled by" in content or re.search(r"\*\*.+\*\* - <@", content):
        #    logger.debug(f"Message {message.id} content pattern matches upscale.")
        #    return True

        # 3. 버튼 구성 확인 (옵션 - 더 안정적일 수 있음)
        # 예: U1-U4 버튼이 없고, V1-V4 또는 Reroll 버튼 등이 있는 경우
        # has_variation_buttons = False
        # if message.components:
        #     for action_row in message.components:
        #         for component in action_row.children:
        #             if isinstance(component, discord.Button) and component.label and component.label.startswith("V"):
        #                 has_variation_buttons = True
        #                 break
        #         if has_variation_buttons: break
        # if has_variation_buttons:
        #     logger.debug(f"Message {message.id} has variation buttons, likely upscale.")
        #     return True

        # 현재: 이미지 첨부파일이 있으면 일단 True 반환 (가장 단순한 방식)
        logger.debug(f"Message {message.id} has image attachment, considering it as potentially upscaled.")
        return True

    async def process_midjourney_message(self, message: discord.Message):
        """Midjourney 메시지를 처리하는 공통 로직"""
        # 1. 설정된 서버/채널/봇 ID와 일치하는지 확인
        if not config.MIDJOURNEY_BOT_ID or message.author.id != config.MIDJOURNEY_BOT_ID:
            return
        if not message.guild: # DM 메시지는 처리 안 함
            return

        # 서버/채널 확인
        target_guild = self.get_target_guild()
        # 봇이 해당 서버에 있는지, 메시지가 온 서버가 맞는지 확인
        if not target_guild or message.guild.id != target_guild.id:
            return
        target_channel = self.get_target_channel(target_guild)
        # 메시지가 온 채널이 맞는지 확인
        if not target_channel or message.channel.id != target_channel.id:
            return

        logger.debug(f"Midjourney bot message detected in target channel: {message.id}")

        # 2. 업스케일된 이미지 메시지인지 추정
        if not self.is_upscaled_image_message(message):
             logger.debug(f"Message {message.id} is not considered an upscaled image.")
             return

        # 3. 이미지 URL 추출
        image_url = self.extract_image_url(message)
        if not image_url:
            logger.warning(f"Upscaled-like message {message.id} detected, but failed to extract image URL.")
            return

        logger.info(f"Upscaled Midjourney image URL found: {image_url} (Message ID: {message.id})")

        # 4. Notion 페이지 ID 가져오기 (봇 상태에서 가장 최근 ID 가져오기)
        page_id_from_state = self.get_latest_diary_page_id_from_bot()

        # 5. Notion 페이지 업데이트 시도
        target_page_id = page_id_from_state
        if target_page_id:
            logger.info(f"Found latest diary page ID from bot state: {target_page_id}. Attempting update.")
        else:
            # 봇 상태에 ID가 없으면 Notion DB에서 직접 최신 ID 조회 (Fallback)
            logger.warning(f"Could not find a page ID in bot state. Querying Notion DB for the latest diary page.")
            try:
                page_id_from_db = await self.notion_service.get_latest_diary_page_id()
                if page_id_from_db:
                     target_page_id = page_id_from_db
                     logger.info(f"Found latest diary page ID from DB: {target_page_id}. Attempting update.")
                else:
                    logger.error(f"Could not find any latest diary page ID from Notion DB for image {image_url}.")
                    return # 업데이트할 페이지 ID가 없으므로 종료
            except Exception as db_e:
                 logger.error(f"Error fetching latest diary page ID from Notion DB: {db_e}", exc_info=True)
                 return # DB 조회 오류 시 종료

        # 업데이트할 페이지 ID가 있으면 Notion 서비스 호출
        if target_page_id:
            try:
                success = await self.notion_service.update_diary_image(target_page_id, image_url)
                if success:
                    logger.info(f"Successfully updated Notion page {target_page_id} with image {image_url}")
                    # 성공 시, 사용된 페이지 ID를 bot 상태에서 제거하거나 업데이트할 수 있음
                    # 예: self.bot.last_diary_page_ids.pop(channel_id_where_diary_was_created, None)
                    # 이 로직은 상태 관리 방식에 따라 추가 구현 필요
                else:
                     logger.error(f"Notion service reported failure updating page {target_page_id} with image {image_url}")
            except Exception as e:
                logger.error(f"Error calling Notion service to update page {target_page_id}: {e}", exc_info=True)


    # --- Event Listeners ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Midjourney 봇이 새 메시지를 보냈을 때 처리"""
        # 봇 메시지만 처리
        if not message.author.bot:
            return
        # process_midjourney_message 내부에서 봇 ID, 서버, 채널 필터링 수행
        await self.process_midjourney_message(message)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        """Midjourney 봇이 메시지를 수정했을 때 처리"""
        # Raw 이벤트 데이터에서 필요한 정보 확인
        if 'author' not in payload.data or 'id' not in payload.data['author'] or payload.data['author']['id'] != str(config.MIDJOURNEY_BOT_ID):
             return
        if 'channel_id' not in payload.data:
             return

        try:
            # 캐시된 메시지 사용 시도 (없으면 API 호출)
            message = payload.cached_message
            if not message:
                channel = self.bot.get_channel(payload.channel_id)
                # 채널 존재 및 TextChannel 타입 확인
                if not channel or not isinstance(channel, discord.TextChannel):
                    logger.warning(f"Could not find text channel for raw message edit: {payload.channel_id}")
                    return
                # 메시지 가져오기
                message = await channel.fetch_message(payload.message_id)

            if message:
                logger.debug(f"Processing raw message edit for message: {message.id}")
                await self.process_midjourney_message(message)
            else:
                 logger.warning(f"Could not get message object for raw message edit: {payload.message_id}")

        except discord.NotFound:
            logger.warning(f"Message {payload.message_id} not found during raw edit processing.")
        except discord.Forbidden:
             logger.warning(f"Missing permissions to fetch message {payload.message_id} during raw edit processing.")
        except Exception as e:
            logger.error(f"Error processing raw message edit for {payload.message_id}: {e}", exc_info=True)


# Cog를 봇에 추가하기 위한 필수 설정 함수
async def setup(bot: 'KiyoBot'):
    await bot.add_cog(MidjourneyCog(bot))
    logger.info("MidjourneyCog has been loaded.")
