import logging
import re
from datetime import datetime, time, date, timedelta
from typing import Optional, List, Dict, Any
import discord # is_target_user에서 discord.User 타입 힌트 위해
from dateutil.parser import parse as dateutil_parse # dateutil.parser 임포트
from dateutil.relativedelta import relativedelta, SU, MO, TU, WE, TH, FR, SA # relativedelta 및 요일 상수 임포트

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

def parse_natural_date_string(natural_date_str: str, base_datetime: Optional[datetime] = None) -> Optional[datetime]:
    """
    "내일 오전 9시", "다음 주 월요일", "모레 오후 3시 30분", "5월 20일" 등
    자연어 날짜/시간 문자열을 파싱하여 KST 기준 datetime 객체로 변환합니다.

    Args:
        natural_date_str: 파싱할 자연어 날짜/시간 문자열.
        base_datetime: 상대 날짜 계산의 기준이 될 datetime 객체 (기본값: 현재 KST 시간).

    Returns:
        파싱 성공 시 KST로 현지화된 datetime 객체, 실패 시 None.
    """
    if not natural_date_str:
        return None

    text_to_parse = natural_date_str.strip()
    ref_dt = base_datetime or datetime.now(config.KST) # 기준 시간 (KST)
    
    # 기본 시간 설정 (날짜만 언급 시 사용될 수 있는 시간)
    default_time = time(9, 0) # 예: "내일" -> 내일 오전 9시

    parsed_dt_naive: Optional[datetime] = None # 시간대 정보가 없는 datetime

    # 1. 간단한 상대 날짜 처리 (오늘, 내일, 모레, 어제, 그저께)
    #    시간 정보가 함께 있을 수 있으므로, 날짜 부분만 먼저 처리하고 시간은 dateutil에 맡기거나 후처리
    specific_date_part: Optional[date] = None
    time_text_part = text_to_parse # 시간 처리를 위해 원본 텍스트 유지

    if "오늘" in text_to_parse:
        specific_date_part = ref_dt.date()
        time_text_part = text_to_parse.replace("오늘", "").strip()
    elif "내일" in text_to_parse:
        specific_date_part = (ref_dt + timedelta(days=1)).date()
        time_text_part = text_to_parse.replace("내일", "").strip()
    elif "모레" in text_to_parse:
        specific_date_part = (ref_dt + timedelta(days=2)).date()
        time_text_part = text_to_parse.replace("모레", "").strip()
    elif "어제" in text_to_parse:
        specific_date_part = (ref_dt - timedelta(days=1)).date()
        time_text_part = text_to_parse.replace("어제", "").strip()
    elif "그저께" in text_to_parse or "그제" in text_to_parse:
        specific_date_part = (ref_dt - timedelta(days=2)).date()
        time_text_part = text_to_parse.replace("그저께", "").replace("그제", "").strip()

    # 2. "X요일" 패턴 처리 (예: "다음 주 월요일", "이번 주 수요일", 그냥 "금요일")
    # dateutil.relativedelta를 사용하여 요일 계산
    day_keywords = {"월": MO, "화": TU, "수": WE, "목": TH, "금": FR, "토": SA, "일": SU}
    day_match = re.search(r"(다음\s*주|이번\s*주)?\s*([월화수목금토일])(?:요일)?", text_to_parse)

    if day_match and not specific_date_part: # 요일 패턴이 있고, 아직 날짜가 결정 안 됐으면
        prefix, day_char = day_match.groups()
        target_weekday_obj = day_keywords.get(day_char)

        if target_weekday_obj:
            if prefix == "다음 주":
                specific_date_part = (ref_dt + relativedelta(weeks=1, weekday=target_weekday_obj(-1))).date()
            elif prefix == "이번 주":
                specific_date_part = (ref_dt + relativedelta(weekday=target_weekday_obj(-1))).date()
            else: # "다음 주"나 "이번 주" 없이 요일만 언급 (예: "금요일")
                  # 현재 주 또는 다음 주의 해당 요일 중 가장 가까운 미래 시점
                temp_date = ref_dt + relativedelta(weekday=target_weekday_obj)
                if temp_date.date() < ref_dt.date(): # 이미 지난 요일이면 다음 주로
                    temp_date = ref_dt + relativedelta(weeks=1, weekday=target_weekday_obj)
                specific_date_part = temp_date.date()
            
            # 요일 관련 텍스트를 제거하여 시간 파싱 용이하게 함
            time_text_part = text_to_parse.replace(day_match.group(0), "").strip()


    # 3. dateutil.parser.parse 시도
    #    time_text_part는 "오늘", "내일" 등이 제거된 문자열이거나, 원본 문자열
    #    specific_date_part가 있으면 그것을 기본 날짜로 사용
    try:
        if specific_date_part:
            # 날짜는 이미 특정되었고, 시간 정보만 time_text_part에서 파싱 시도
            if time_text_part: # 시간 관련 텍스트가 남아있다면
                # dateutil.parse에 날짜 정보 없이 시간만 넘기면 현재 날짜를 사용하므로,
                # 기준 날짜(specific_date_part)와 합치기 위해 default 설정
                parsed_time_info = dateutil_parse(time_text_part, default=datetime.combine(specific_date_part, time(0,0)), fuzzy_with_tokens=False)
                parsed_dt_naive = datetime.combine(specific_date_part, parsed_time_info.time())
            else: # 날짜만 있고 시간 언급이 없으면 기본 시간 사용
                parsed_dt_naive = datetime.combine(specific_date_part, default_time)
        else:
            # specific_date_part가 없는 경우 (예: "5월 20일 오후 3시")
            # dateutil이 전체 문자열 파싱 시도
            # fuzzy_with_tokens=True는 "내일 오후 3시에 할 일" 같은 문장에서 "할 일" 등을 무시
            # 다만, 여기서는 AI가 이미 어느 정도 정제된 due_date_description을 줄 것이므로 False로 해도 무방
            parsed_dt_naive = dateutil_parse(text_to_parse, default=ref_dt.replace(hour=default_time.hour, minute=default_time.minute, second=0, microsecond=0), fuzzy_with_tokens=False)

    except (ValueError, TypeError, dateutil_parse.ParserError) as e:
        logger.warning(f"dateutil.parser could not parse '{text_to_parse}' (time_text_part: '{time_text_part}'): {e}")
        return None # 파싱 실패 시

    # 4. 시간대 정보 적용 (KST)
    if parsed_dt_naive:
        if parsed_dt_naive.tzinfo is None:
            # logger.debug(f"Parsed naive datetime: {parsed_dt_naive}, localizing to KST.")
            return config.KST.localize(parsed_dt_naive)
        else: # 이미 시간대 정보가 있다면 KST로 변환
            # logger.debug(f"Parsed timezone-aware datetime: {parsed_dt_naive}, converting to KST.")
            return parsed_dt_naive.astimezone(config.KST)

    logger.warning(f"Could not parse natural date string into datetime: '{natural_date_str}'")
    return None

# 필요에 따라 다른 헬퍼 함수 추가 가능
# 예: def format_notion_rich_text(text): return [{"type": "text", "text": {"content": text}}]
# 예: def get_kst_now(): return datetime.now(config.KST)
