import discord
from discord.ext import commands
import logging
import re
from typing import Optional

import config

# --- Service Imports ---
# from services.notion_service import NotionService

# --- 임시 Service Placeholder ---
class PlaceholderNotionService:
    async def update_diary_image(self, page_id, image_url):
        logger.info(f"Notion page {page_id} cover/image updated with {image_url} (Placeholder)")
    async def get_latest_diary_page_id(self): # Notion DB에서 마지막 페이지 ID 가져오는 함수 (실제 구현 필요)
        logger.warning("Using dummy page ID from placeholder get_latest_diary_page_id")
        return "dummy_page_id_from_db_query"

# --- Logger ---
logger = logging.getLogger(__name__)

class MidjourneyCog(commands.Cog, name="Midjourney Listener"):
    """Midjourney 봇 메시지를 감지하고 Notion 일기와 연동"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # --- 서비스 인스턴스 주입 ---
        # self.notion_service: NotionService = bot.notion_service
        self.notion_service = PlaceholderNotionService() # 임시 Placeholder 사용

        # --- 상태 접근 (Bot 객체에 위임 가정) ---
        # self.bot.last_diary_page_ids = {} 가 client.py에서 초기화되었다고 가정

    def get_target_guild(self) -> Optional[discord.Guild]:
        """설정된 서버 이름으로 Guild 객체를 찾습니다."""
        if not config.MIDJOURNEY_SERVER_NAME:
            return None
        return discord.utils.get(self.bot.guilds, name=config.MIDJOURNEY_SERVER_NAME)

    def get_target_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        """설정된 채널 이름으로 TextChannel 객체를 찾습니다."""
        if not guild or not config.MIDJOURNEY_CHANNEL_NAME:
            return None
        # 채널 이름으로만 찾음 (더 정확하게는 ID 사용 권장)
        return discord.utils.get(guild.text_channels, name=config.MIDJOURNEY_CHANNEL_NAME)

    def get_latest_diary_page_id_from_bot(self) -> Optional[str]:
        """봇 객체에 저장된 마지막 일기 페이지 ID 중 가장 최신 것을 반환 (임시 로직)"""
        if hasattr(self.bot, 'last_diary_page_ids') and self.bot.last_diary_page_ids:
            # 실제로는 채널별 ID 중 어떤 것을 선택할지 정책이 필요함
            # 여기서는 가장 마지막에 저장된 ID를 반환한다고 가정
            latest_channel_id = list(self.bot.last_diary_page_ids.keys())[-1]
            page_id = self.bot.last_diary_page_ids.get(latest_channel_id)
            if page_id:
                logger.debug(f"Retrieved latest diary page ID: {page_id} (from channel {latest_channel_id})")
                return page_id
        logger.warning("No last diary page ID found stored in bot object.")
        return None

    def extract_image_url(self, message: discord.Message) -> Optional[str]:
        """메시지 첨부파일 또는 임베드에서 이미지 URL 추출"""
        if message.attachments:
            for attachment in message.attachments:
                # URL에서 쿼리 스트링 제거 (CDN 캐시 등 때문에)
                url_without_query = attachment.url.split("?")[0]
                # 이미지 확장자 확인
                if url_without_query.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    logger.debug(f"Image URL extracted from attachment: {attachment.url}")
                    return attachment.url
        # 첨부파일이 없으면 임베드 확인 (Midjourney는 임베드도 자주 사용)
        if message.embeds:
            for embed in message.embeds:
                if embed.image and embed.image.url:
                    logger.debug(f"Image URL extracted from embed image: {embed.image.url}")
                    return embed.image.url
                # 썸네일도 확인해볼 수 있음
                # if embed.thumbnail and embed.thumbnail.url:
                #    logger.debug(f"Image URL extracted from embed thumbnail: {embed.thumbnail.url}")
                #    return embed.thumbnail.url
        logger.debug(f"No image URL found in message {message.id}")
        return None

    def is_upscaled_image_message(self, message: discord.Message) -> bool:
        """메시지가 업스케일된 최종 이미지 결과인지 추정 (개선 필요)"""
        # 원본 코드의 Regex 방식은 버튼 등이 포함된 메시지도 감지할 수 있음
        # return bool(re.search(r"Image\s+#\d", message.content))

        # 좀 더 개선된 방식:
        # 1. 메시지 내용에 특정 키워드(예: "Upscaled by")나 패턴 확인
        # 2. 버튼 구성 확인 (예: U1~U4 버튼이 없고 V1~V4, Reroll 등만 있는 경우)
        # 3. 첨부파일이 있고, 임베드가 특정 형태를 띠는 경우 등
        # 여기서는 단순하게 첨부파일이 '있는지' 여부만 우선 확인 (개선 필요)
        if message.attachments:
            # 추가로 메시지 내용이나 버튼 유무 등으로 더 정확히 판단 가능
            # 예: if "Variations" in message.content or "Upscaled" in message.content: return True
            logger.debug(f"Message {message.id} has attachments, potentially an upscaled image.")
            return True
        # MJ가 메시지를 수정하여 이미지를 추가하는 경우도 있으므로 on_raw_message_edit도 중요
        logger.debug(f"Message {message.id} has no attachments, likely not a final upscaled image message.")
        return False

    async def process_midjourney_message(self, message: discord.Message):
        """Midjourney 메시지를 처리하는 공통 로직"""
        # 1. 설정된 서버/채널/봇 ID와 일치하는지 확인
        if not config.MIDJOURNEY_BOT_ID or message.author.id != config.MIDJOURNEY_BOT_ID:
            return

        target_guild = self.get_target_guild()
        if not target_guild or message.guild != target_guild:
            return

        target_channel = self.get_target_channel(target_guild)
        if not target_channel or message.channel != target_channel:
            return

        logger.debug(f"Midjourney bot message detected in target channel: {message.id}")

        # 2. 업스케일된 이미지 메시지인지 추정
        # (is_upscaled_image_message 로직 개선 필요)
        if not self.is_upscaled_image_message(message):
             logger.debug(f"Message {message.id} is not considered an upscaled image.")
             return

        # 3. 이미지 URL 추출
        image_url = self.extract_image_url(message)
        if not image_url:
            logger.warning(f"Upscaled message {message.id} detected, but failed to extract image URL.")
            return

        logger.info(f"Upscaled Midjourney image URL found: {image_url} (Message ID: {message.id})")

        # 4. Notion 페이지 ID 가져오기 (현재: 가장 최근 ID / 개선 필요)
        page_id = self.get_latest_diary_page_id_from_bot()

        # 5. Notion 페이지 업데이트 시도
        if page_id:
            try:
                # Notion 서비스의 update_diary_image 호출 (페이지 ID, 이미지 URL 전달)
                await self.notion_service.update_diary_image(page_id, image_url)
                logger.info(f"Successfully requested Notion update for page {page_id} with image {image_url}")
                # 성공 시, 사용된 페이지 ID를 bot 상태에서 제거하거나 업데이트할 수 있음
                # 예: self.bot.last_diary_page_ids.pop(channel_id_where_diary_was_created, None)
            except Exception as e:
                logger.error(f"Failed to update Notion page {page_id} with image {image_url}: {e}", exc_info=True)
        else:
            # 만약 Notion 페이지 ID를 찾지 못했다면?
            # 1. Notion DB에서 직접 마지막 일기 페이지를 찾는 로직 추가 (Notion 서비스에 구현)
            logger.warning(f"Could not find a recent diary page ID to associate with image {image_url}. Trying to fetch latest from DB.")
            try:
                page_id_from_db = await self.notion_service.get_latest_diary_page_id()
                if page_id_from_db:
                    await self.notion_service.update_diary_image(page_id_from_db, image_url)
                    logger.info(f"Successfully updated LATEST Notion page {page_id_from_db} from DB with image {image_url}")
                else:
                    logger.error(f"Could not find any page ID from DB either for image {image_url}.")
            except Exception as e:
                 logger.error(f"Error trying to update latest Notion page from DB: {e}", exc_info=True)


    # --- Event Listeners ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Midjourney 봇이 새 메시지를 보냈을 때 처리"""
        # 봇 메시지, 명령어 등 기본 필터링은 GeneralCog에서 처리 가정
        if message.author.bot: # 다른 봇 메시지 포함하여 봇 메시지면 일단 처리 로직 호출
            await self.process_midjourney_message(message)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        """Midjourney 봇이 메시지를 수정했을 때 처리 (예: 버튼 추가, 이미지 임베드 변경)"""
        # Raw 이벤트는 메시지 객체가 아닌 payload를 받으므로, 필요한 정보 추출 필요
        if 'author' not in payload.data or payload.data['author']['id'] != str(config.MIDJOURNEY_BOT_ID):
             return
        if 'channel_id' not in payload.data:
             return

        try:
            channel = self.bot.get_channel(payload.channel_id)
            if not channel or not isinstance(channel, discord.TextChannel):
                # 채널 정보를 찾을 수 없거나 DM 채널 등 예상치 못한 경우
                logger.warning(f"Could not find text channel for raw message edit: {payload.channel_id}")
                return

            message = await channel.fetch_message(payload.message_id)
            logger.debug(f"Processing raw message edit for message: {message.id}")
            await self.process_midjourney_message(message)

        except discord.NotFound:
            logger.warning(f"Message {payload.message_id} not found during raw edit processing.")
        except discord.Forbidden:
             logger.warning(f"Missing permissions to fetch message {payload.message_id} during raw edit processing.")
        except Exception as e:
            logger.error(f"Error processing raw message edit for {payload.message_id}: {e}", exc_info=True)


# Cog를 봇에 추가하기 위한 필수 설정 함수
async def setup(bot: commands.Bot):
    await bot.add_cog(MidjourneyCog(bot))
    logger.info("MidjourneyCog has been loaded.")
