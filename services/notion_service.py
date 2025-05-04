import aiohttp
import asyncio
import logging
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import config # 설정 임포트
from utils.helpers import parse_time_string # 시간 파싱 헬퍼 임포트 (utils/helpers.py에 구현 필요)

logger = logging.getLogger(__name__)

# --- Notion API Base URL ---
NOTION_API_BASE_URL = "https://api.notion.com/v1"

class NotionAPIError(Exception):
    """Notion API 호출 관련 커스텀 오류"""
    def __init__(self, status_code: int, error_code: Optional[str], message: str):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        super().__init__(f"Notion API Error ({status_code}): [{error_code}] {message}")

class NotionService:
    """
    Notion API와의 비동기 상호작용을 담당하는 서비스 클래스.
    aiohttp를 사용하여 API를 호출합니다.
    """

    def __init__(self):
        if not config.NOTION_API_KEY:
            logger.critical("Notion API Key is not configured. NotionService cannot function.")
            raise ValueError("Notion API Key not configured.")

        self._headers = {
            "Authorization": f"Bearer {config.NOTION_API_KEY}",
            "Notion-Version": config.NOTION_API_VERSION,
            "Content-Type": "application/json"
        }
        # aiohttp ClientSession 관리
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock() # 세션 생성/닫기 동기화용

    async def _get_session(self) -> aiohttp.ClientSession:
        """aiohttp ClientSession을 생성하거나 기존 세션을 반환합니다."""
        async with self._session_lock:
            if self._session is None or self._session.closed:
                # trace_configs 설정하여 상세한 요청/응답 로깅 가능 (디버깅 시 유용)
                # trace_config = aiohttp.TraceConfig()
                # trace_config.on_request_start.append(on_request_start) # 로깅 콜백 함수 정의 필요
                # trace_config.on_request_end.append(on_request_end)
                self._session = aiohttp.ClientSession(headers=self._headers) #, trace_configs=[trace_config])
                logger.info("Created new aiohttp ClientSession for NotionService.")
            return self._session

    async def close_session(self):
        """aiohttp ClientSession을 안전하게 닫습니다."""
        async with self._session_lock:
            if self._session and not self._session.closed:
                await self._session.close()
                self._session = None
                logger.info("Closed aiohttp ClientSession for NotionService.")

    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Notion API에 비동기 요청을 보내고 결과를 처리하는 내부 메소드"""
        session = await self._get_session()
        url = f"{NOTION_API_BASE_URL}/{endpoint.lstrip('/')}"
        # kwargs에 기본 헤더 외 추가 헤더가 있으면 병합 (거의 사용 안 함)
        # headers = self._headers.copy()
        # if 'headers' in kwargs:
        #     headers.update(kwargs.pop('headers'))

        try:
            async with session.request(method, url, **kwargs) as response:
                # 응답 상태 코드 확인
                if 200 <= response.status < 300:
                    try:
                        json_response = await response.json()
                        logger.debug(f"Notion API Success ({method} {url} - {response.status})")
                        return json_response
                    except aiohttp.ContentTypeError:
                        logger.error(f"Notion API response is not valid JSON ({method} {url} - {response.status})")
                        raise NotionAPIError(response.status, "invalid_json", "Response was not valid JSON.")
                else:
                    # API 오류 처리
                    try:
                        error_data = await response.json()
                        error_code = error_data.get("code", "unknown_error")
                        error_message = error_data.get("message", "No error message provided.")
                    except Exception:
                        error_code = "parsing_error"
                        error_message = await response.text() # JSON 파싱 실패 시 텍스트라도 가져옴

                    logger.error(f"Notion API Error ({method} {url} - {response.status}): [{error_code}] {error_message}")
                    raise NotionAPIError(response.status, error_code, error_message)

        except aiohttp.ClientError as e:
            logger.error(f"Notion API connection error ({method} {url}): {e}", exc_info=True)
            raise NotionAPIError(503, "connection_error", f"Failed to connect to Notion API: {e}")
        except asyncio.TimeoutError:
             logger.error(f"Notion API request timed out ({method} {url})")
             raise NotionAPIError(408, "timeout", "Request to Notion API timed out.")


    # --- Helper Functions for Payload Creation ---
    def _format_rich_text(self, content: str) -> List[Dict[str, Any]]:
        """Notion rich_text 객체 생성"""
        return [{"type": "text", "text": {"content": content}}]

    def _format_date(self, dt: datetime) -> Dict[str, Any]:
        """Notion date 객체 생성 (YYYY-MM-DD)"""
        return {"start": dt.strftime("%Y-%m-%d")}

    # --- Diary Methods ---
    async def upload_diary_entry(self, text: str, emotion_key: str, style: str, image_url: Optional[str] = None) -> Optional[str]:
        """Notion 일기 데이터베이스에 새 페이지 생성"""
        if not config.NOTION_DIARY_DB_ID:
            logger.error("NOTION_DIARY_DB_ID is not set. Cannot upload diary.")
            return None

        diary_date = datetime.now(config.KST)
        date_str = diary_date.strftime("%Y년 %m월 %d일 일기") + f" ({style})"
        iso_date = diary_date.strftime("%Y-%m-%d")
        tags = config.EMOTION_TAGS.get(emotion_key, ["기록"]) # config에서 태그 가져옴
        time_info = diary_date.strftime("%p %I:%M").replace("AM", "오전").replace("PM", "오후")

        properties = {
            "Name": {"title": self._format_rich_text(date_str)},
            "날짜": {"date": self._format_date(diary_date)},
            "태그": {"multi_select": [{"name": tag} for tag in tags]}
            # 필요시 다른 속성 추가 (예: "스타일": {"select": {"name": style}})
        }

        # 페이지 본문 블록 구성
        children = [
            { # 작성 시간 정보 블록
                "object": "block", "type": "quote",
                "quote": {"rich_text": self._format_rich_text(f"🕰️ 작성 시간: {time_info} | 스타일: {style}")}
            },
            # 이미지 블록은 update_diary_image에서 추가
            { # 일기 본문 블록
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": self._format_rich_text(text)}
            }
        ]

        payload = {
            "parent": {"database_id": config.NOTION_DIARY_DB_ID},
            "properties": properties,
            "children": children
        }

        # 커버 이미지 추가
        if image_url:
            payload["cover"] = {"type": "external", "external": {"url": image_url}}

        try:
            response = await self._request('POST', 'pages', json=payload)
            page_id = response.get("id")
            logger.info(f"Successfully created diary entry in Notion (Page ID: {page_id})")
            return page_id
        except NotionAPIError as e:
            logger.error(f"Failed to upload diary entry to Notion: {e}")
            return None

    async def update_diary_image(self, page_id: str, image_url: str) -> bool:
        """기존 Notion 일기 페이지에 커버 및 이미지 블록 업데이트/추가"""
        if not page_id: return False

        update_payload = {
            "cover": {"type": "external", "external": {"url": image_url}}
        }
        append_payload = {
            "children": [{
                "object": "block", "type": "image",
                "image": {"type": "external", "external": {"url": image_url}}
            }]
        }

        try:
            # 1. 커버 업데이트 (PATCH)
            await self._request('PATCH', f'pages/{page_id}', json=update_payload)
            logger.info(f"Updated cover image for Notion page {page_id}")

            # 2. 이미지 블록 추가 (POST to children)
            await self._request('POST', f'blocks/{page_id}/children', json=append_payload)
            logger.info(f"Appended image block to Notion page {page_id}")
            return True
        except NotionAPIError as e:
            logger.error(f"Failed to update diary image for Notion page {page_id}: {e}")
            return False

    async def get_latest_diary_page_id(self) -> Optional[str]:
         """가장 최근에 생성된 일기 페이지 ID 조회"""
         if not config.NOTION_DIARY_DB_ID: return None
         payload = {
             "page_size": 1,
             "sorts": [{"property": "날짜", "direction": "descending"}] # "날짜" 속성 이름 확인 필요
         }
         try:
             response = await self._request('POST', f'databases/{config.NOTION_DIARY_DB_ID}/query', json=payload)
             results = response.get("results", [])
             if results:
                 page_id = results[0].get("id")
                 logger.debug(f"Found latest diary page ID from DB: {page_id}")
                 return page_id
             else:
                 logger.warning("No diary pages found in the database.")
                 return None
         except NotionAPIError as e:
             logger.error(f"Failed to fetch latest diary page ID: {e}")
             return None

    async def fetch_recent_diary_summary(self, limit: int = 3) -> Optional[str]:
        """최근 일기 몇 개의 본문 요약 조회 (AI 컨텍스트용)"""
        if not config.NOTION_DIARY_DB_ID: return "Notion 일기 DB가 설정되지 않음."
        query_payload = {
            "page_size": limit,
            "sorts": [{"property": "날짜", "direction": "descending"}]
        }
        summaries = []
        try:
            db_response = await self._request('POST', f'databases/{config.NOTION_DIARY_DB_ID}/query', json=query_payload)
            pages = db_response.get("results", [])
            if not pages: return "최근 일기가 없음."

            for page in pages:
                page_id = page.get("id")
                if not page_id: continue
                try:
                    block_response = await self._request('GET', f'blocks/{page_id}/children')
                    children = block_response.get("results", [])
                    page_text = ""
                    for child in children:
                        if child.get("type") == "paragraph":
                            rich_text = child.get("paragraph", {}).get("rich_text", [])
                            for rt in rich_text:
                                page_text += rt.get("plain_text", "")
                    if page_text:
                        # 간단하게 앞부분만 요약으로 사용
                        summaries.append(page_text[:150] + "...")
                except NotionAPIError as block_e:
                    logger.warning(f"Failed to fetch blocks for diary page {page_id}: {block_e}")

            if not summaries: return "최근 일기 내용을 불러올 수 없음."
            return "\n\n".join(reversed(summaries)) # 시간순으로 반환

        except NotionAPIError as db_e:
            logger.error(f"Failed to fetch recent diary summaries: {db_e}")
            return f"최근 일기 요약 조회 실패: {db_e.message}"

    # --- Observation Methods ---
    async def upload_observation(self, text: str, title: str, tags: List[str]):
        """Notion 관찰 기록 데이터베이스에 새 페이지 생성"""
        if not config.NOTION_OBSERVATION_DB_ID:
            logger.error("NOTION_OBSERVATION_DB_ID is not set. Cannot upload observation.")
            return

        obs_date = datetime.now(config.KST)
        properties = {
            "이름": {"title": self._format_rich_text(title)}, # "이름" 속성 이름 확인 필요
            "날짜": {"date": self._format_date(obs_date)},   # "날짜" 속성 이름 확인 필요
            "태그": {"multi_select": [{"name": tag} for tag in tags]} # "태그" 속성 이름 확인 필요
        }

        # 텍스트를 소제목(예: "1. ...") 기준으로 파싱하여 블록 생성
        blocks = []
        # 정규식으로 소제목 분리 (기존 코드와 유사하게)
        # 주의: 정규식은 텍스트 형식에 따라 민감하게 작동하므로 테스트 필요
        sections = re.split(r"^\s*(\d+\.\s+.+?)\s*$", text, flags=re.MULTILINE)
        content_parts = [s.strip() for s in sections if s and s.strip()]

        current_heading = None
        for part in content_parts:
            if re.match(r"^\d+\.\s+", part): # 소제목인 경우
                current_heading = part
                blocks.append({
                    "object": "block", "type": "heading_2", # heading_3 사용도 가능
                    "heading_2": {"rich_text": self._format_rich_text(current_heading)}
                })
            elif current_heading: # 소제목 다음의 내용인 경우
                 blocks.append({
                    "object": "block", "type": "paragraph",
                    "paragraph": {"rich_text": self._format_rich_text(part)}
                 })
                 current_heading = None # 내용 추가 후 초기화
            else: # 소제목 없이 시작하는 내용 (서론 등)
                blocks.append({
                    "object": "block", "type": "paragraph",
                    "paragraph": {"rich_text": self._format_rich_text(part)}
                })


        payload = {
            "parent": {"database_id": config.NOTION_OBSERVATION_DB_ID},
            "properties": properties,
            "children": blocks if blocks else [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": self._format_rich_text(text)}}] # 파싱 실패 시 원본 텍스트
        }

        try:
            response = await self._request('POST', 'pages', json=payload)
            page_id = response.get("id")
            logger.info(f"Successfully created observation entry in Notion (Page ID: {page_id})")
            return page_id
        except NotionAPIError as e:
            logger.error(f"Failed to upload observation entry to Notion: {e}")
            return None

    async def fetch_recent_observations(self, limit: int = 5) -> Optional[str]:
        """최근 관찰 기록 조회 (AI 컨텍스트용)"""
        if not config.NOTION_OBSERVATION_DB_ID: return "Notion 관찰 DB가 설정되지 않음."
        query_payload = {
            "page_size": limit,
            "sorts": [{"property": "날짜", "direction": "descending"}]
        }
        all_obs_texts = []
        try:
            db_response = await self._request('POST', f'databases/{config.NOTION_OBSERVATION_DB_ID}/query', json=query_payload)
            pages = db_response.get("results", [])
            if not pages: return "최근 관찰 기록이 없음."

            for page in pages:
                page_id = page.get("id")
                if not page_id: continue
                try:
                    block_response = await self._request('GET', f'blocks/{page_id}/children')
                    children = block_response.get("results", [])
                    page_text = ""
                    for child in children:
                        block_type = child.get("type")
                        if block_type in ["paragraph", "heading_2", "heading_3", "quote", "bulleted_list_item", "numbered_list_item"]:
                           rich_text = child.get(block_type, {}).get("rich_text", [])
                           for rt in rich_text:
                               page_text += rt.get("plain_text", "") + "\n" # 블록 내용 합치기
                    if page_text:
                        all_obs_texts.append(page_text.strip())
                except NotionAPIError as block_e:
                    logger.warning(f"Failed to fetch blocks for observation page {page_id}: {block_e}")

            if not all_obs_texts: return "최근 관찰 기록 내용을 불러올 수 없음."
            # 최신 기록이 마지막에 오도록 reversed 사용
            return "\n\n---\n\n".join(reversed(all_obs_texts)) # 각 기록 구분

        except NotionAPIError as db_e:
            logger.error(f"Failed to fetch recent observations: {db_e}")
            return f"최근 관찰 기록 조회 실패: {db_e.message}"


    # --- Memory Methods ---
    async def upload_memory(self, original_text: str, summary: str, message_url: Optional[str] = None,
                          tags: Optional[List[str]] = None, category: str = "기억", status: str = "기억 중"):
        """Notion 기억 데이터베이스에 새 페이지 생성"""
        if not config.NOTION_MEMORY_DB_ID:
            logger.error("NOTION_MEMORY_DB_ID is not set. Cannot upload memory.")
            return None

        memory_date = datetime.now(config.KST)
        properties = {
            "기억 내용": {"title": self._format_rich_text(summary)}, # DB 속성 이름 확인
            "전체 문장": {"rich_text": self._format_rich_text(original_text)}, # DB 속성 이름 확인
            "날짜": {"date": self._format_date(memory_date)}, # DB 속성 이름 확인
            "카테고리": {"select": {"name": category}}, # DB 속성 이름 확인
            "상태": {"select": {"name": status}}, # DB 속성 이름 확인
        }
        if tags:
            properties["태그"] = {"multi_select": [{"name": tag} for tag in tags]} # DB 속성 이름 확인
        if message_url:
            properties["연결된 대화 ID"] = {"url": message_url} # DB 속성 이름 확인

        payload = {
            "parent": {"database_id": config.NOTION_MEMORY_DB_ID},
            "properties": properties
            # 기억 DB는 본문(children)이 필요 없을 수 있음
        }

        try:
            response = await self._request('POST', 'pages', json=payload)
            page_id = response.get("id")
            logger.info(f"Successfully created memory entry in Notion (Page ID: {page_id})")
            return page_id
        except NotionAPIError as e:
            logger.error(f"Failed to upload memory entry to Notion: {e}")
            return None

    async def fetch_recent_memories(self, limit: int = 5) -> Optional[List[str]]:
        """최근 기억 조회 (AI 컨텍스트용)"""
        if not config.NOTION_MEMORY_DB_ID: return ["Notion 기억 DB가 설정되지 않음."]
        payload = {
            "page_size": limit,
            "sorts": [{"property": "날짜", "direction": "descending"}]
        }
        summaries = []
        try:
            response = await self._request('POST', f'databases/{config.NOTION_MEMORY_DB_ID}/query', json=payload)
            pages = response.get("results", [])
            if not pages: return ["최근 기억 없음."]

            for page in pages:
                # '기억 내용' 속성에서 title 텍스트 추출
                title_prop = page.get("properties", {}).get("기억 내용", {}).get("title", [])
                if title_prop:
                    summaries.append(title_prop[0].get("plain_text", "내용 없음"))

            return summaries if summaries else ["최근 기억 내용 없음."]

        except NotionAPIError as e:
            logger.error(f"Failed to fetch recent memories: {e}")
            return [f"최근 기억 조회 실패: {e.message}"]


    # --- ToDo Methods ---
    async def fetch_pending_todos(self) -> List[Dict[str, Any]]:
        """완료되지 않은 오늘 할 일 목록 조회"""
        if not config.NOTION_TODO_DB_ID: return []

        now = datetime.now(config.KST)
        today_weekday = now.strftime("%a") # 예: 'Mon', 'Tue' (Notion 요일 속성과 일치하는지 확인 필요)

        # 필터 구성 (기존 코드 참고하되, Notion API 문서 확인 필요)
        daily_filter = {"property": "반복", "select": {"equals": "매일"}}
        weekly_filter = {
            "and": [
                {"property": "반복", "select": {"equals": "매주"}},
                {"property": "요일", "multi_select": {"contains": today_weekday}}
            ]
        }
        # 날짜 필터 (오늘 날짜 또는 반복 없는 경우?) - 필요시 추가
        # no_repeat_filter = {"property": "반복", "select": {"is_empty": True}}
        # date_filter = {"property": "날짜", "date": {"equals": now.strftime("%Y-%m-%d")}}

        query_filter = {
             "filter": {
                 "and": [
                     {"property": "완료 여부", "checkbox": {"equals": False}}, # "완료 여부" 속성 이름 확인
                     {"or": [daily_filter, weekly_filter]} # 매일 또는 해당 요일 매주
                     # 필요시 날짜 필터, 반복 없음 필터 추가
                 ]
             }
             # 필요시 정렬 추가
             # "sorts": [{"property": "시간대", "direction": "ascending"}]
        }

        try:
            response = await self._request('POST', f'databases/{config.NOTION_TODO_DB_ID}/query', json=query_filter)
            all_pending = response.get("results", [])

            # 시간 기반 필터링 (구체적인 시간 있는 항목만) - 로직 재확인 필요
            valid_tasks = []
            current_time = now.time()

            for page in all_pending:
                props = page.get("properties", {})
                time_str_list = props.get("구체적인 시간", {}).get("rich_text", []) # "구체적인 시간" 속성 확인
                parsed_time = None
                if time_str_list:
                    time_str = time_str_list[0].get("plain_text", "").strip()
                    parsed_time = parse_time_string(time_str) # utils.helpers에 구현 필요

                if parsed_time and parsed_time <= current_time:
                    # 시간이 지정되어 있고, 현재 시간 이전인 경우만 포함
                    valid_tasks.append(page)
                elif not parsed_time:
                     # 시간이 지정되지 않은 경우 일단 포함 (시간대별 리마인더용)
                     valid_tasks.append(page)

            logger.info(f"Fetched {len(valid_tasks)} pending todo(s) for today.")
            return valid_tasks

        except NotionAPIError as e:
            logger.error(f"Failed to fetch pending todos: {e}")
            return []

    async def update_task_completion(self, page_id: str, is_done: bool):
        """할 일 완료 여부 업데이트"""
        if not page_id: return False
        payload = {
            "properties": {
                "완료 여부": {"checkbox": is_done} # "완료 여부" 속성 이름 확인
            }
        }
        try:
            await self._request('PATCH', f'pages/{page_id}', json=payload)
            status = "completed" if is_done else "pending"
            logger.info(f"Updated task {page_id} completion status to {status}.")
            return True
        except NotionAPIError as e:
            logger.error(f"Failed to update task completion for {page_id}: {e}")
            return False

    async def reset_daily_todos(self):
        """매일 자정에 반복 할 일들의 완료 여부를 False로 초기화"""
        if not config.NOTION_TODO_DB_ID:
            logger.warning("NOTION_TODO_DB_ID not set. Cannot reset daily todos.")
            return

        logger.info("Starting daily todo reset process...")
        now = datetime.now(config.KST)
        today_weekday = now.strftime("%a")

        # 완료된 항목 중, 매일 반복이거나 오늘 요일인 매주 반복 항목 필터링
        query_filter = {
            "filter": {
                "and": [
                    {"property": "완료 여부", "checkbox": {"equals": True}}, # 어제 완료된 항목 대상
                    {"or": [
                        {"property": "반복", "select": {"equals": "매일"}},
                        {
                            "and": [
                                {"property": "반복", "select": {"equals": "매주"}},
                                {"property": "요일", "multi_select": {"contains": today_weekday}}
                            ]
                        }
                    ]}
                ]
            }
        }
        reset_count = 0
        try:
            # 페이지네이션 처리 필요할 수 있음 (한 번에 100개 이상 처리 시)
            response = await self._request('POST', f'databases/{config.NOTION_TODO_DB_ID}/query', json=query_filter)
            pages_to_reset = response.get("results", [])

            if not pages_to_reset:
                logger.info("No completed repeating todos found to reset.")
                return

            # 각 페이지 완료 여부 업데이트
            tasks = []
            for page in pages_to_reset:
                page_id = page.get("id")
                if page_id:
                    tasks.append(self.update_task_completion(page_id, False)) # 비동기 작업 리스트 생성

            # 여러 업데이트 작업을 동시에 실행
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 결과 확인
            for i, result in enumerate(results):
                page_id = pages_to_reset[i].get("id")
                if isinstance(result, Exception):
                    logger.error(f"Failed to reset todo {page_id}: {result}")
                elif result is True:
                    reset_count += 1

            logger.info(f"Successfully reset {reset_count} out of {len(pages_to_reset)} repeating todos.")

        except NotionAPIError as e:
            logger.error(f"Error during daily todo reset query: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during daily todo reset: {e}", exc_info=True)

    # mark_reminder_sent 등 다른 유틸리티 함수 필요시 여기에 비동기로 구현


# NotionService 인스턴스 생성 (싱글턴처럼 사용 가능)
# notion_service_instance = NotionService()

# 다른 모듈에서 사용 예시:
# from .notion_service import notion_service_instance
# await notion_service_instance.upload_diary_entry(...)
# 앱 종료 시: await notion_service_instance.close_session() 필요
