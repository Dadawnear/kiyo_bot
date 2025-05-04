import logging
import re
from datetime import datetime, time
from typing import Optional, List, Dict, Any
import discord # is_target_user에서 discord.User 타입 힌트 위해

import config # 설정 임포트

logger = logging.getLogger(__name__)

def parse_time_string(time_str: str) -> Optional[time]:
    """
    "HH:MM" 형식의 시간 문자열을 파싱하여 datetime.time 객체로 반환합니다.
    파싱 실패 시 None을 반환합니다.
    """
    if not time_str:
        return None
    try:
        # 다양한 형식 지원 가능 (예: "HH시 MM분") - 필요시 정규식 등 사용
        parsed_time = datetime.strptime(time_str.strip(), "%H:%M").time()
        # logger.debug(f"Parsed time string '{time_str}' to {parsed_time}")
        return parsed_time
    except ValueError:
        logger.warning(f"Failed to parse time string: '{time_str}'. Expected HH:MM format.")
        return None

def group_todos_by_timeblock(todos: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Notion 할 일 페이지 목록을 시간대('시간대' 속성 기준)별로 그룹핑합니다.

    Args:
        todos: Notion API에서 조회한 할 일 페이지 객체 리스트.

    Returns:
        시간대 이름을 키로 하고, 해당 시간대의 할 일 정보(title, page_id) 리스트를 값으로 하는 딕셔너리.
    """
    grouped = {}
    default_block = "기타" # 시간대 속성이 없거나 비어있는 경우

    for todo in todos:
        page_id = todo.get("id")
        properties = todo.get("properties", {})

        # 시간대 정보 추출 ('시간대' 속성 이름 및 타입 확인 필요)
        timeblock_prop = properties.get("시간대", {}).get("select", {})
        timeblock_name = timeblock_prop.get("name") if timeblock_prop else default_block

        # 할 일 제목 추출 ('할 일' 속성 이름 및 타입 확인 필요)
        title_prop = properties.get("할 일", {}).get("title", [])
        title = title_prop[0].get("plain_text", "(제목 없음)") if title_prop else "(제목 없음)"

        # 그룹핑된 딕셔너리에 추가
        if timeblock_name not in grouped:
            grouped[timeblock_name] = []
        grouped[timeblock_name].append({
            "title": title,
            "page_id": page_id
            # 필요시 다른 정보 추가 (예: 완료 여부, 구체적인 시간 등)
        })

    logger.debug(f"Grouped {len(todos)} todos into {len(grouped)} timeblocks: {list(grouped.keys())}")
    return grouped

def is_target_user(author: discord.User | discord.Member) -> bool:
    """
    주어진 사용자가 설정 파일에 정의된 대상 사용자인지 확인합니다.

    Args:
        author: 확인할 discord 사용자 또는 멤버 객체.

    Returns:
        대상 사용자이면 True, 아니면 False. 설정이 없으면 True 반환 (주의).
    """
    if not author: # 혹시 author가 None일 경우 대비
        return False

    if config.TARGET_USER_ID:
        return author.id == config.TARGET_USER_ID
    elif config.TARGET_USER_DISCORD_NAME:
        # USER_DISCORD_NAME 형식은 'username#discriminator' 또는 'new_username'
        return str(author) == config.TARGET_USER_DISCORD_NAME or author.name == config.TARGET_USER_DISCORD_NAME
    else:
        # 대상 사용자가 설정되지 않은 경우, 모든 사용자를 대상으로 간주할지 여부 결정 필요
        logger.warning("Target user (USER_ID or USER_DISCORD_NAME) is not configured. is_target_user check will allow everyone.")
        return True # 또는 False로 변경하여 기능 제한

# 필요에 따라 다른 헬퍼 함수 추가 가능
# 예: def format_notion_text_block(text): ...
# 예: def get_kst_now(): return datetime.now(config.KST)
