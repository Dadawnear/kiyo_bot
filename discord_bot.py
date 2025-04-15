import os
import discord
import asyncio
from dotenv import load_dotenv
from kiyo_brain import (
    generate_kiyo_message, summarize_conversation,
    generate_morning_greeting, generate_lunch_checkin,
    generate_evening_checkin, generate_night_checkin
)
from notion_utils import upload_to_notion, fetch_recent_notion_summary
from scheduler import setup_scheduler

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
USER_DISCORD_NAME = os.getenv("USER_DISCORD_NAME")

client = discord.Client(intents=discord.Intents.all())
conversation_log = []

def is_target_user(message):
    return str(message.author) == USER_DISCORD_NAME

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    setup_scheduler()

@client.event
async def on_message(message):
    if message.author == client.user or not is_target_user(message):
        return

    conversation_log.append(("정서영", message.content))
    response = await generate_kiyo_message(conversation_log)
    conversation_log.append(("キヨ", response))
    await message.channel.send(response)

    if len(conversation_log) >= 6:
        summary = await summarize_conversation(conversation_log)
        await upload_to_notion(summary)
        conversation_log.clear()

async def send_greeting_with_prompt(prompt_func):
    for guild in client.guilds:
        for member in guild.members:
            if str(member) == USER_DISCORD_NAME:
                try:
                    channel = await member.create_dm()
                    notion_summary = await fetch_recent_notion_summary()
                    message = await prompt_func(notion_summary)
                    await channel.send(message)
                    conversation_log.append(("キヨ", message))
                except Exception as e:
                    print("Failed to send message:", e)

# 각각 시간대별 메시지 함수
async def send_morning_greeting():
    await send_greeting_with_prompt(generate_morning_greeting)

async def send_lunch_checkin():
    await send_greeting_with_prompt(generate_lunch_checkin)

async def send_evening_checkin():
    await send_greeting_with_prompt(generate_evening_checkin)

async def send_night_checkin():
    await send_greeting_with_prompt(generate_night_checkin)

async def send_daily_summary():
    if conversation_log:
        summary = await summarize_conversation(conversation_log)
        await upload_to_notion(summary)
        conversation_log.clear()

async def start_discord_bot():
    await client.start(DISCORD_BOT_TOKEN)
