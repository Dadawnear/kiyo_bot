import aiohttp
import asyncio
import logging
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import config # 설정 임포트
# utils.helpers는 아래 코드 내에서 직접 사용하지 않으므로 주석 처리
# 만약 시간 파싱 등 필요하면 활성화
from utils.helpers import parse_time_string

logger = logging.getLogger(__name__)

# --- Notion API Base URL ---
NOTION_API_BASE_URL = "https://api.notion.com/v1"

# --- Custom Error ---
class NotionAPIError(Exception):
    """Notion API 호출 관련 커스텀 오류"""
    def __init__(self, status_code: int, error_code: Optional[str] = None, message: Optional[str] = None):
        self.status_code = status_code
        self.error_code = error_code or "unknown_error"
        self.message = message or "An unspecified Notion API error occurred."
        super().__init__(f"Notion API Error ({status_code}): [{self.error_code}] {self.message}")

# --- Service Class ---
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
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        """aiohttp ClientSession을 생성하거나 기존 세션을 반환합니다."""
        async with self._session_lock:
            if self._session is None or self._session.closed:
                # 타임아웃 설정 추가 (예: 총 30초, 소켓 연결 10초)
                timeout = aiohttp.ClientTimeout(total=30, connect=10)
                self._session = aiohttp.ClientSession(headers=self._headers, timeout=timeout)
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

        retry_attempts = 3 # 재시도 횟수
        base_delay = 1 # 재시도 기본 대기 시간 (초)

        for attempt in range(retry_attempts):
            try:
                logger.debug(f"Sending Notion API request ({method} {url}) attempt {attempt + 1}/{retry_attempts}")
                # logger.debug(f"Request Data: {kwargs.get('json')}") # 필요시 요청 데이터 로깅
                async with session.request(method, url, **kwargs) as response:
                    if 200 <= response.status < 300:
                        try:
                            json_response = await response.json()
                            logger.debug(f"Notion API Success ({method} {url} - {response.status})")
                            return json_response
                        except aiohttp.ContentTypeError:
                             logger.error(f"Notion API response is not valid JSON ({method} {url} - {response.status})")
                             raise NotionAPIError(response.status, "invalid_json", "Response was not valid JSON.")

                    # 오류 응답 처리
                    error_data = {}
                    error_text = await response.text() # 오류 메시지 확인 위해 텍스트 먼저 읽기
                    try:
                        error_data = await response.json() # JSON 파싱 재시도 (오류 구조 확인 위해)
                    except Exception:
                        logger.warning(f"Could not parse Notion API error response as JSON. Body: {error_text[:500]}...") # 너무 길면 잘라서 로깅

                    error_code = error_data.get("code", "unknown_api_error")
                    error_message = error_data.get("message", error_text) # JSON 파싱 실패 시 텍스트 사용

                    # 재시도 가능한 오류인지 확인 (예: 429 Rate Limit, 500 Internal Server Error, 503 Service Unavailable, 504 Gateway Timeout)
                    if response.status in [429, 500, 503, 504] and attempt < retry_attempts - 1:
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 1) # Exponential backoff with jitter
                        logger.warning(f"Notion API Error ({method} {url} - {response.status}). Retrying in {delay:.2f} seconds... (Code: {error_code})")
                        await asyncio.sleep(delay)
                        continue # 다음 재시도
                    else:
                        # 재시도 불가 오류 또는 마지막 재시도 실패
                        logger.error(f"Notion API Error ({method} {url} - {response.status}): [{error_code}] {error_message}")
                        raise NotionAPIError(response.status, error_code, error_message)

            except aiohttp.ClientError as e:
                logger.error(f"Notion API connection error ({method} {url}): {e}", exc_info=True)
                # 연결 오류 시 재시도 가능성 있음 (선택적)
                if attempt < retry_attempts - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"Connection error. Retrying in {delay:.2f} seconds...")
                    await asyncio.sleep(delay)
                    continue
                else:
                    raise NotionAPIError(503, "connection_error", f"Failed to connect to Notion API after {retry_attempts} attempts: {e}")
            except asyncio.TimeoutError:
                 logger.error(f"Notion API request timed out ({method} {url})")
                 # 타임아웃 시 재시도 가능성 있음 (선택적)
                 if attempt < retry_attempts - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"Request timed out. Retrying in {delay:.2f} seconds...")
                    await asyncio.sleep(delay)
                    continue
                 else:
                    raise NotionAPIError(408, "timeout", f"Request to Notion API timed out after {retry_attempts} attempts.")
            except Exception as e: # 그 외 예외
                logger.exception(f"Unexpected error during Notion API request ({method} {url}): {e}")
                raise NotionAPIError(500, "internal_client_error", f"An unexpected error occurred: {e}")

        # 재시도 모두 실패 시
        raise NotionAPIError(500, "max_retries_exceeded", f"Request failed after {retry_attempts} attempts.")

    # --- Helper Functions for Payload Creation ---
    def _format_rich_text(self, content: str) -> List[Dict[str, Any]]:
        """Notion rich_text 객체 생성"""
        return [{"type": "text", "text": {"content": str(content)}}] # content가 숫자인 경우 대비 str()

    def _format_date(self, dt: Optional[datetime]) -> Optional[Dict[str, Any]]:
        """Notion date 객체 생성 (YYYY-MM-DD)"""
        if dt is None:
            return None
        return {"start": dt.strftime("%Y-%m-%d")}

    def _format_datetime(self, dt: Optional[datetime]) -> Optional[Dict[str, Any]]:
         """Notion datetime 객체 생성 (ISO 8601)"""
         if dt is None:
             return None
         # Notion은 UTC 기준 ISO 8601 형식을 요구함
         # KST datetime 객체를 UTC로 변환 후 포맷팅
         # return {"start": dt.astimezone(timezone.utc).isoformat()}
         # 또는 KST 정보 포함하여 전송 (Notion이 해석)
         return {"start": dt.isoformat()} # KST 정보 포함됨

    # --- Diary Methods ---
    async def upload_diary_entry(self, text: str, emotion_key: str, style: str, image_url: Optional[str] = None) -> Optional[str]:
        """Notion 일기 데이터베이스에 새 페이지 생성"""
        if not config.NOTION_DIARY_DB_ID:
            logger.error("NOTION_DIARY_DB_ID is not set. Cannot upload diary.")
            return None

        diary_date = datetime.now(config.KST)
        # Notion 속성 이름 확인 필수!
        title_prop_name = "Name" # 실제 Notion DB의 제목 속성 이름
        date_prop_name = "날짜"
        tags_prop_name = "태그"

        date_str = diary_date.strftime("%Y년 %m월 %d일 일기") + f" ({style})"
        tags = config.EMOTION_TAGS.get(emotion_key, ["기록"])
        time_info = diary_date.strftime("%p %I:%M %Z").replace("AM", "오전").replace("PM", "오후")

        properties = {
            title_prop_name: {"title": self._format_rich_text(date_str)},
            date_prop_name: {"date": self._format_date(diary_date)},
            tags_prop_name: {"multi_select": [{"name": tag} for tag in tags]}
            # 추가 속성 예시: "스타일": {"select": {"name": style}}
        }

        children = [
            {"object": "block", "type": "quote", "quote": {"rich_text": self._format_rich_text(f"🕰️ 작성 시간: {time_info} | 스타일: {style}")}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": self._format_rich_text(text)}}
        ]

        payload = {
            "parent": {"database_id": config.NOTION_DIARY_DB_ID},
            "properties": properties,
            "children": children
        }
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
        if not page_id or not image_url: return False
        logger.info(f"Attempting to update Notion page {page_id} with image {image_url}")

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
            # 커버 업데이트와 블록 추가를 동시에 시도 (하나 실패해도 다른 건 시도됨)
            update_task = self._request('PATCH', f'pages/{page_id}', json=update_payload)
            append_task = self._request('POST', f'blocks/{page_id}/children', json=append_payload)

            results = await asyncio.gather(update_task, append_task, return_exceptions=True)

            success = True
            if isinstance(results[0], Exception):
                logger.error(f"Failed to update cover image for Notion page {page_id}: {results[0]}")
                success = False
            else:
                 logger.info(f"Updated cover image for Notion page {page_id}")

            if isinstance(results[1], Exception):
                logger.error(f"Failed to append image block to Notion page {page_id}: {results[1]}")
                success = False
            else:
                 logger.info(f"Appended image block to Notion page {page_id}")

            return success # 둘 다 성공해야 True 반환 (또는 하나라도 성공하면 True 반환?)

        except Exception as e: # gather 자체 오류 등
            logger.error(f"Unexpected error updating diary image for Notion page {page_id}: {e}", exc_info=True)
            return False

    async def get_latest_diary_page_id(self) -> Optional[str]:
         """가장 최근에 생성된 일기 페이지 ID 조회"""
         if not config.NOTION_DIARY_DB_ID: return None
         # Notion 속성 이름 확인!
         date_prop_name = "날짜"
         payload = {
             "page_size": 1,
             "sorts": [{"property": date_prop_name, "direction": "descending"}]
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
        date_prop_name = "날짜" # Notion 속성 이름 확인!
        query_payload = {
            "page_size": limit,
            "sorts": [{"property": date_prop_name, "direction": "descending"}]
        }
        summaries = []
        try:
            db_response = await self._request('POST', f'databases/{config.NOTION_DIARY_DB_ID}/query', json=query_payload)
            pages = db_response.get("results", [])
            if not pages: return "최근 일기가 없음."

            fetch_tasks = [self._request('GET', f'blocks/{page.get("id")}/children') for page in pages if page.get("id")]
            block_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            for i, result in enumerate(block_results):
                if isinstance(result, Exception):
                     logger.warning(f"Failed to fetch blocks for diary page {pages[i].get('id')}: {result}")
                     continue

                children = result.get("results", [])
                page_text = ""
                for child in children:
                    block_type = child.get("type")
                    if block_type == "paragraph": # 본문 내용만 가져오도록 수정
                        rich_text = child.get(block_type, {}).get("rich_text", [])
                        for rt in rich_text:
                            page_text += rt.get("plain_text", "")
                if page_text:
                    summaries.append(page_text[:200].strip() + "...") # 요약 길이 조정

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
            return None

        # Notion 속성 이름 확인 필수!
        title_prop_name = "이름"
        date_prop_name = "날짜"
        tags_prop_name = "태그"

        obs_date = datetime.now(config.KST)
        properties = {
            title_prop_name: {"title": self._format_rich_text(title)},
            date_prop_name: {"date": self._format_date(obs_date)},
            tags_prop_name: {"multi_select": [{"name": tag} for tag in tags]}
        }

        # 텍스트를 소제목 기준으로 파싱하여 블록 생성 (개선된 로직)
        blocks = []
        current_content = ""
        for line in text.splitlines():
            stripped_line = line.strip()
            if not stripped_line: continue # 빈 줄 무시

            heading_match = re.match(r"^\s*(\d+\.\s+.+?)\s*$", stripped_line)
            if heading_match:
                # 이전 내용이 있으면 paragraph 블록으로 추가
                if current_content:
                    blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": self._format_rich_text(current_content.strip())}})
                    current_content = ""
                # 새 heading 블록 추가
                blocks.append({
                    "object": "block", "type": "heading_2",
                    "heading_2": {"rich_text": self._format_rich_text(heading_match.group(1))}
                })
            else:
                 current_content += line + "\n" # 일반 내용은 누적

        # 마지막 남은 내용 추가
        if current_content:
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": self._format_rich_text(current_content.strip())}})

        # 블록 생성 실패 시 원본 텍스트 사용
        if not blocks:
            blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": self._format_rich_text(text)}}]

        payload = {
            "parent": {"database_id": config.NOTION_OBSERVATION_DB_ID},
            "properties": properties,
            "children": blocks
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
        date_prop_name = "날짜" # Notion 속성 이름 확인!
        query_payload = {
            "page_size": limit,
            "sorts": [{"property": date_prop_name, "direction": "descending"}]
        }
        all_obs_texts = []
        try:
            db_response = await self._request('POST', f'databases/{config.NOTION_OBSERVATION_DB_ID}/query', json=query_payload)
            pages = db_response.get("results", [])
            if not pages: return "최근 관찰 기록이 없음."

            fetch_tasks = [self._request('GET', f'blocks/{page.get("id")}/children') for page in pages if page.get("id")]
            block_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            for i, result in enumerate(block_results):
                 if isinstance(result, Exception):
                     logger.warning(f"Failed to fetch blocks for observation page {pages[i].get('id')}: {result}")
                     continue

                 children = result.get("results", [])
                 page_text = ""
                 for child in children:
                     block_type = child.get("type")
                     content_dict = child.get(block_type, {})
                     rich_text = content_dict.get("rich_text", []) if isinstance(content_dict, dict) else []
                     if rich_text:
                         block_content = "".join([rt.get("plain_text", "") for rt in rich_text])
                         if block_type.startswith("heading"):
                              page_text += f"## {block_content}\n" # 마크다운 형식으로 추가
                         else:
                              page_text += block_content + "\n"
                 if page_text:
                     all_obs_texts.append(page_text.strip())

            if not all_obs_texts: return "최근 관찰 기록 내용을 불러올 수 없음."
            return "\n\n---\n\n".join(reversed(all_obs_texts)) # 시간순으로 반환

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

        # Notion 속성 이름 확인 필수!
        summary_prop_name = "기억 내용"
        text_prop_name = "전체 문장"
        date_prop_name = "날짜"
        category_prop_name = "카테고리"
        status_prop_name = "상태"
        tags_prop_name = "태그"
        url_prop_name = "연결된 대화 ID"

        memory_date = datetime.now(config.KST)
        properties = {
            summary_prop_name: {"title": self._format_rich_text(summary)},
            text_prop_name: {"rich_text": self._format_rich_text(original_text)},
            date_prop_name: {"date": self._format_date(memory_date)},
            category_prop_name: {"select": {"name": category}},
            status_prop_name: {"select": {"name": status}},
        }
        if tags:
            properties[tags_prop_name] = {"multi_select": [{"name": tag} for tag in tags]}
        if message_url:
            properties[url_prop_name] = {"url": message_url}

        payload = {
            "parent": {"database_id": config.NOTION_MEMORY_DB_ID},
            "properties": properties
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
        date_prop_name = "날짜" # Notion 속성 이름 확인!
        summary_prop_name = "기억 내용" # Notion 속성 이름 확인!
        payload = {
            "page_size": limit,
            "sorts": [{"property": date_prop_name, "direction": "descending"}]
        }
        summaries = []
        try:
            response = await self._request('POST', f'databases/{config.NOTION_MEMORY_DB_ID}/query', json=payload)
            pages = response.get("results", [])
            if not pages: return ["최근 기억 없음."]

            for page in pages:
                title_prop = page.get("properties", {}).get(summary_prop_name, {}).get("title", [])
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

        # Notion 속성 이름 확인 필수!
        completion_prop_name = "완료 여부"
        repeat_prop_name = "반복"
        day_prop_name = "요일"

        now = datetime.now(config.KST)
        today_weekday = now.strftime("%a") # 예: 'Mon', 'Tue'

        daily_filter = {"property": repeat_prop_name, "select": {"equals": "매일"}}
        weekly_filter = {
            "and": [
                {"property": repeat_prop_name, "select": {"equals": "매주"}},
                {"property": day_prop_name, "multi_select": {"contains": today_weekday}}
            ]
        }
        # 날짜 필터 추가 (반복되지 않고 오늘 날짜인 항목)
        date_prop_name = "날짜"
        today_date_str = now.strftime("%Y-%m-%d")
        no_repeat_today_filter = {
             "and": [
                 {"property": repeat_prop_name, "select": {"is_empty": True}},
                 {"property": date_prop_name, "date": {"equals": today_date_str}}
             ]
        }


        query_payload = {
             "filter": {
                 "and": [
                     {"property": completion_prop_name, "checkbox": {"equals": False}},
                     {"or": [daily_filter, weekly_filter, no_repeat_today_filter]} # 매일, 매주(오늘), 오늘 할 일(반복X)
                 ]
             }
             # 필요시 정렬 추가
        }

        try:
            # 페이지네이션 처리 추가 (결과가 100개 이상일 경우)
            all_pending_todos = []
            start_cursor = None
            while True:
                 if start_cursor:
                     query_payload["start_cursor"] = start_cursor

                 response = await self._request('POST', f'databases/{config.NOTION_TODO_DB_ID}/query', json=query_payload)
                 results = response.get("results", [])
                 all_pending_todos.extend(results)

                 if response.get("has_more"):
                     start_cursor = response.get("next_cursor")
                 else:
                     break

            logger.info(f"Fetched {len(all_pending_todos)} total pending todo(s) for today.")
            return all_pending_todos

        except NotionAPIError as e:
            logger.error(f"Failed to fetch pending todos: {e}")
            return []

    async def update_task_completion(self, page_id: str, is_done: bool):
        """할 일 완료 여부 업데이트"""
        if not page_id: return False
        completion_prop_name = "완료 여부" # Notion 속성 이름 확인!
        payload = {
            "properties": {
                completion_prop_name: {"checkbox": is_done}
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
        # Notion 속성 이름 확인 필수!
        completion_prop_name = "완료 여부"
        repeat_prop_name = "반복"
        day_prop_name = "요일"

        now = datetime.now(config.KST)
        today_weekday = now.strftime("%a")

        query_payload = {
            "filter": {
                "and": [
                    {"property": completion_prop_name, "checkbox": {"equals": True}}, # 완료된 항목 대상
                    {"or": [
                        {"property": repeat_prop_name, "select": {"equals": "매일"}},
                        {
                            "and": [
                                {"property": repeat_prop_name, "select": {"equals": "매주"}},
                                {"property": day_prop_name, "multi_select": {"contains": today_weekday}}
                            ]
                        }
                    ]}
                ]
            }
        }
        reset_count = 0
        try:
            # 페이지네이션 처리
            pages_to_reset = []
            start_cursor = None
            while True:
                 if start_cursor:
                     query_payload["start_cursor"] = start_cursor
                 response = await self._request('POST', f'databases/{config.NOTION_TODO_DB_ID}/query', json=query_payload)
                 results = response.get("results", [])
                 pages_to_reset.extend(results)
                 if response.get("has_more"):
                     start_cursor = response.get("next_cursor")
                 else:
                     break

            if not pages_to_reset:
                logger.info("No completed repeating todos found to reset.")
                return

            tasks = [self.update_task_completion(page.get("id"), False) for page in pages_to_reset if page.get("id")]
            results = await asyncio.gather(*tasks, return_exceptions=True)

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

    # --- 필요시 추가 Notion 관련 메소드 구현 ---
    # 예: async def generate_observation_title(self, text: str) -> str: ...
    # 예: async def generate_observation_tags(self, text: str) -> List[str]: ...
    # (AI 서비스에서 처리하거나, Notion API 직접 호출하여 관련 페이지 정보 가져오는 등)
