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
        # "%H:%M" 형식으로 파싱 시도
        parsed_time = datetime.strptime(time_str.strip(), "%H:%M").time()
        # logger.debug(f"Parsed time string '{time_str}' to {parsed_time}")
        return parsed_time
    except ValueError:
        # 다른 형식 시도 (예: "H:MM", "HH:M") - 필요시 추가
        # logger.warning(f"Failed to parse time string: '{time_str}'. Expected HH:MM format.")
        # 더 많은 형식을 지원하려면 정규식 사용 고려
        match = re.match(r"(\d{1,2}):(\d{1,2})", time_str.strip())
        if match:
            try:
                hour, minute = int(match.group(1)), int(match.group(2))
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    return time(hour, minute)
                else:
                     logger.warning(f"Invalid time value in '{time_str}'.")
                     return None
            except ValueError: # int 변환 실패 등
                 logger.warning(f"Could not parse time components in '{time_str}'.")
                 return None
        else:
            logger.warning(f"Time string '{time_str}' does not match expected HH:MM format.")
            return None


def group_todos_by_timeblock(todos: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Notion 할 일 페이지 목록을 시간대('시간대' 속성 기준)별로 그룹핑합니다.

    Args:
        todos: Notion API에서 조회한 할 일 페이지 객체 리스트.

    Returns:
        시간대 이름을 키로 하고, 해당 시간대의 할 일 정보(title, page_id) 리스트를 값으로 하는 딕셔너리.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    default_block = "기타" # 시간대 속성이 없거나 비어있는 경우

    for todo in todos:
        page_id = todo.get("id")
        properties = todo.get("properties", {})
        if not page_id or not properties: # 필수 정보 없으면 건너뛰기
             logger.warning(f"Skipping todo item due to missing id or properties: {todo.get('id', 'N/A')}")
             continue

        # 시간대 정보 추출 ('시간대' 속성 이름 및 타입 확인 필요)
        timeblock_prop = properties.get("시간대", {}).get("select") # Select 객체 가져오기
        timeblock_name = timeblock_prop.get("name") if timeblock_prop else default_block

        # 할 일 제목 추출 ('할 일' 속성 이름 및 타입 확인 필요)
        title_prop = properties.get("할 일", {}).get("title", []) # Title은 리스트 형태
        title = title_prop[0].get("plain_text", "(제목 없음)") if title_prop else "(제목 없음)"

        # 그룹핑된 딕셔너리에 추가
        if timeblock_name not in grouped:
            grouped[timeblock_name] = []

        # 필요한 정보만 추출하여 저장
        todo_info = {
            "title": title,
            "page_id": page_id
            # 필요시 다른 속성 추가 (예: properties 전체 저장)
            # "properties": properties # 디버깅 또는 추가 정보 필요시
        }
        grouped[timeblock_name].append(todo_info)

    # 디버그 로그 개선: 그룹별 개수 포함
    group_counts = {k: len(v) for k, v in grouped.items()}
    logger.debug(f"Grouped {len(todos)} todos into {len(grouped)} timeblocks: {group_counts}")
    return grouped

def is_target_user(author: Optional[discord.User | discord.Member]) -> bool:
    """
    주어진 사용자가 설정 파일에 정의된 대상 사용자인지 확인합니다.

    Args:
        author: 확인할 discord 사용자 또는 멤버 객체. None일 수도 있음.

    Returns:
        대상 사용자이면 True, 아니면 False. 설정이 없으면 True 반환 (주의).
    """
    if not author:
        logger.debug("is_target_user called with None author.")
        return False

    # 설정값 확인
    target_id = config.TARGET_USER_ID
    target_name = config.TARGET_USER_DISCORD_NAME

    if target_id:
        # ID가 설정되어 있으면 ID로 비교
        is_target = (author.id == target_id)
        # logger.debug(f"Checking user ID: {author.id} == {target_id} -> {is_target}")
        return is_target
    elif target_name:
        # ID 없고 이름만 설정되어 있으면 이름으로 비교
        # Discord 사용자 이름 형식 변경 고려: 'username#1234' 또는 'username'
        is_target = (str(author) == target_name or author.name == target_name)
        # logger.debug(f"Checking user name: '{str(author)}' or '{author.name}' == '{target_name}' -> {is_target}")
        return is_target
    else:
        # 대상 사용자가 설정되지 않은 경우
        logger.warning("Target user (USER_ID or USER_DISCORD_NAME) is not configured in .env. is_target_user check will allow everyone.")
        # 이 경우 모든 사용자를 허용할지 결정해야 함 (현재: True)
        # 보안상 False로 변경하고 필수 설정으로 만드는 것을 권장
        return True

# 필요에 따라 다른 헬퍼 함수 추가 가능
# 예: def format_notion_rich_text(text): return [{"type": "text", "text": {"content": text}}]
# 예: def get_kst_now(): return datetime.now(config.KST)
