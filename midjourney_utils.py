import os
import logging
import discord

async def send_midjourney_prompt(client, prompt_text):
    try:
        server_name = os.getenv("DISCORD_SERVER_NAME", "SNKY")
        channel_name = os.getenv("MIDJOURNEY_CHANNEL_NAME", "midjourney-image-channel")
        midjourney_bot_id = os.getenv("MIDJOURNEY_BOT_ID")  # 예: "936929561302675456"
        if not midjourney_bot_id:
            logging.error("[MJ] MIDJOURNEY_BOT_ID가 .env에 설정되지 않았어.")
            return

        # ✅ 프롬프트에 스타일 자동 추가
        style_suffix = "cinematic kodak film photo --ar 3:2"
        full_prompt = f"{prompt_text}, {style_suffix}"

        # 정확한 서버 지정
        guild = discord.utils.get(client.guilds, name=server_name)
        if not guild:
            logging.error(f"[MJ] 서버를 찾을 수 없어: {server_name}")
            return

        # 정확한 채널 지정
        channel = discord.utils.get(guild.text_channels, name=channel_name)
        if not channel:
            logging.error(f"[MJ] 채널을 찾을 수 없어: {channel_name}")
            return

        mention_prompt = f"<@{midjourney_bot_id}> imagine prompt: {full_prompt}"
        await channel.send(mention_prompt)
        logging.info(f"[MJ] 프롬프트 전송 성공 (멘션 방식): {full_prompt}")

    except Exception as e:
        logging.error(f"[MJ] 프롬프트 전송 실패: {repr(e)}")
