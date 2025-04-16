import discord
import os
import logging

MIDJOURNEY_CHANNEL_NAME = "midjourney-image-channel"

async def send_midjourney_prompt(client: discord.Client, prompt: str):
    """
    SNKY 서버의 midjourney-image-channel에 프롬프트 메시지를 자동 전송한다.
    """
    try:
        # 서버 순회
        for guild in client.guilds:
            if guild.name == "SNKY":
                for channel in guild.text_channels:
                    if channel.name == MIDJOURNEY_CHANNEL_NAME:
                        await channel.send(f"/imagine prompt: {prompt}")
                        logging.info(f"[MJ] 프롬프트 전송 성공: {prompt}")
                        return
        logging.warning("[MJ] 대상 채널을 찾을 수 없습니다.")
    except Exception as e:
        logging.error(f"[MJ ERROR] 프롬프트 전송 실패: {repr(e)}")
