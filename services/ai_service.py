import os
import aiohttp
import logging
import discord
from openai import AsyncOpenAI, OpenAIError # OpenAI 오류 처리 추가
from datetime import datetime
import random
import difflib
from typing import List, Tuple, Optional, Dict, Any

import config # 설정 임포트
# utils 임포트 (필요시)
# from utils.helpers import some_helper_function
# 서비스 임포트 (필요시)
# from .notion_service import NotionService # 순환 참조 주의! 서비스 간 직접 호출 최소화
# from .weather_service import WeatherService # 날씨 서비스 분리 시

logger = logging.getLogger(__name__)

class AIService:
    """
    LLM (OpenAI 또는 SillyTavern)과의 상호작용을 담당하는 서비스.
    신구지 코레키요 캐릭터의 응답, 일기, 관찰 기록 등 텍스트 생성을 담당합니다.
    """

    def __init__(self):
        # OpenAI 클라이언트 초기화 (API 키가 있는 경우)
        if config.OPENAI_API_KEY:
            self.openai_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
            logger.info("OpenAI client initialized.")
        else:
            self.openai_client = None
            logger.info("OpenAI API Key not found. OpenAI client not initialized.")

        # SillyTavern 설정
        self.use_sillytavern = config.USE_SILLYTAVERN
        self.sillytavern_url = f"{config.SILLYTAVERN_API_BASE}/chat/completions"
        self.sillytavern_model = config.SILLYTAVERN_MODEL_NAME

        if self.use_sillytavern:
            logger.info(f"SillyTavern integration enabled. API endpoint: {config.SILLYTAVERN_API_BASE}, Model: {self.sillytavern_model}")

        # 날씨 서비스 인스턴스 (분리된 경우)
        # self.weather_service = WeatherService()

        # Notion 서비스 인스턴스 (기억/관찰 요약 등 컨텍스트 빌드에 필요한 경우)
        # 순환 참조를 피하기 위해, NotionService가 필요한 데이터를 직접 여기서 호출하기보다,
        # 이 서비스의 메소드를 호출하는 쪽(예: Cog)에서 필요한 데이터를 가져와 인자로 넘겨주는 것이 더 나은 설계일 수 있음.
        # self.notion_service = NotionService() # 직접 초기화는 피하는 것이 좋음

        # --- 캐릭터 관련 설정 ---
        self.face_to_face_channel_id = config.FACE_TO_FACE_CHANNEL_ID
        # 컨텍스트 빌딩에 필요한 상수/설정
        self.user_names_for_prompt = ["정서영", "서영", "너"] # 프롬프트 내 호칭 예시
        # 최근 기억/관찰 내용을 어디서 가져올지 결정 필요 (NotionService 연동 또는 외부 주입)

    async def _call_llm(self, messages: List[Dict[str, Any]], model: Optional[str] = None, temperature: float = 0.7, max_tokens: Optional[int] = None) -> str:
        """LLM API 호출 (OpenAI 또는 SillyTavern)"""
        if self.use_sillytavern:
            # --- SillyTavern 호출 ---
            payload = {
                "model": self.sillytavern_model, # SillyTavern 설정에서 모델 이름 사용
                "messages": messages,
                "temperature": temperature,
                # SillyTavern이 max_tokens를 지원하는지 확인 필요
                # "max_tokens": max_tokens if max_tokens else 1500 # 기본값 설정 예시
            }
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.sillytavern_url, json=payload) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                            logger.debug(f"SillyTavern API response received. Length: {len(content)}")
                            return content.strip()
                        else:
                            error_text = await resp.text()
                            logger.error(f"SillyTavern API error ({resp.status}): {error_text}")
                            return "크크… 지금은 SillyTavern과 연결이 불안정한 것 같아."
            except aiohttp.ClientError as e:
                logger.error(f"SillyTavern API connection error: {e}", exc_info=True)
                return "크크… SillyTavern 서버에 접속할 수 없어."
            except Exception as e:
                 logger.error(f"Error calling SillyTavern API: {e}", exc_info=True)
                 return "크크… SillyTavern API 호출 중 예상치 못한 오류가 발생했어."

        elif self.openai_client:
            # --- OpenAI 호출 ---
            chosen_model = model or config.DEFAULT_LLM_MODEL
            try:
                completion_params = {
                    "model": chosen_model,
                    "messages": messages,
                    "temperature": temperature,
                }
                if max_tokens:
                    completion_params["max_tokens"] = max_tokens

                response = await self.openai_client.chat.completions.create(**completion_params)
                content = response.choices[0].message.content
                logger.debug(f"OpenAI API response received. Model: {chosen_model}, Length: {len(content)}")
                return content.strip()
            except OpenAIError as e:
                logger.error(f"OpenAI API error: {e}", exc_info=True)
                return f"크크… OpenAI API 호출 중 오류가 발생했어. ({e.status_code if hasattr(e, 'status_code') else 'Unknown'})"
            except Exception as e:
                logger.error(f"Error calling OpenAI API: {e}", exc_info=True)
                return "크크… OpenAI API 호출 중 예상치 못한 오류가 발생했어."
        else:
            # 둘 다 사용할 수 없는 경우
            logger.error("No LLM backend available (OpenAI or SillyTavern).")
            return "크크… 지금은 생각을 정리할 수가 없네. (LLM 설정 오류)"

    async def get_current_weather_desc(self) -> Optional[str]:
        """날씨 정보 가져오기 (간단한 경우 여기에, 복잡하면 WeatherService 분리)"""
        # wttr.in 사용 예시 (JSON 포맷)
        url = "https://wttr.in/Mapo?format=j1"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # 현재 날씨 설명 추출 (JSON 구조 확인 필요)
                        condition = data.get("current_condition", [{}])[0]
                        weather_desc = condition.get("weatherDesc", [{}])[0].get("value", "알 수 없음")
                        temp_c = condition.get("temp_C", "?")
                        feels_like_c = condition.get("FeelsLikeC", "?")
                        humidity = condition.get("humidity", "?")
                        precip_mm = condition.get("precipMM", "0") # 강수량

                        # 더 자세한 설명 생성
                        detailed_desc = (
                            f"{weather_desc}, 기온 {temp_c}°C (체감 {feels_like_c}°C), "
                            f"습도 {humidity}%, 강수량 {precip_mm}mm"
                        )
                        logger.debug(f"Fetched weather for Mapo: {detailed_desc}")
                        return detailed_desc
                    else:
                        logger.warning(f"Failed to fetch weather data (status: {resp.status}).")
                        return None
        except aiohttp.ClientError as e:
            logger.error(f"Weather API connection error: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching or parsing weather data: {e}", exc_info=True)
            return None

    async def detect_emotion(self, text: str) -> str:
        """텍스트 기반 감정 추론 (간단한 키워드 방식)"""
        # 더 정확한 감정 분석이 필요하면 LLM 호출 고려
        text_lower = text.lower()
        if any(kw in text_lower for kw in ["외롭", "쓸쓸", "우울", "슬퍼", "힘들"]):
            return "슬픔"
        elif any(kw in text_lower for kw in ["사랑", "보고싶", "좋아", "애정", "행복", "기뻐"]):
            return "애정"
        elif any(kw in text_lower for kw in ["짜증", "미워", "질투", "화나", "분노", "실망"]):
            return "불만_분노"
        elif any(kw in text_lower for kw in ["무기력", "비관", "망상", "이상해"]):
            return "혼란_망상"
        elif any(kw in text_lower for kw in ["고마워", "감사", "안심", "편안"]):
            return "긍정_안정"
        elif any(kw in text_lower for kw in ["불안", "걱정", "무서워", "긴장"]):
             return "불안"
        return "중립_기록" # 기본값

    def get_related_past_message(self, conversation_log: list, current_text: str) -> Optional[str]:
        """현재 대화와 관련된 과거 유저 메시지 찾기 (유사도 기반)"""
        past_user_msgs = [entry[1] for entry in conversation_log[:-1] if len(entry) >= 2 and entry[0] != "キヨ"]
        if not past_user_msgs:
            return None
        # difflib 사용 (간단한 유사도 비교)
        similar = difflib.get_close_matches(current_text, past_user_msgs, n=1, cutoff=0.5) # cutoff 조정 가능
        if similar and random.random() < 0.3: # 30% 확률로 회상
            logger.debug(f"Found related past message using difflib: '{similar[0]}'")
            return similar[0]
        return None

    async def _build_kiyo_context(self, user_text: str = "", conversation_log: Optional[list] = None,
                                recent_memories: Optional[List[str]] = None,
                                recent_observations: Optional[str] = None,
                                recent_diary_summary: Optional[str] = None) -> str:
        """LLM 프롬프트에 주입될 컨텍스트 생성"""
        context_parts = []

        # 1. 시간대 기반 톤
        hour = datetime.now(config.KST).hour
        if 0 <= hour < 6: time_tone = "새벽. 몽환적이고 음산한 분위기, 혼잣말."
        elif 6 <= hour < 11: time_tone = "아침. 느릿하고 다정한 말투, 기상 인사."
        elif 11 <= hour < 14: time_tone = "점심. 식사 걱정, 조용한 말투."
        elif 14 <= hour < 18: time_tone = "오후. 관찰자적이고 여유로운 말투, 민속 이야기."
        elif 18 <= hour < 22: time_tone = "저녁. 피곤함 배려, 부드러운 말투."
        else: time_tone = "밤. 집착, 느리고 나른한 말투."
        context_parts.append(f"현재 시간대: {time_tone}")

        # 2. 날씨 정보
        weather = await self.get_current_weather_desc()
        if weather:
            context_parts.append(f"현재 날씨: {weather}. 날씨 분위기를 반영하라.")

        # 3. 감정 분석 및 톤 지시
        if user_text:
            emotion = await self.detect_emotion(user_text)
            tone_map = {
                "슬픔": "조용하고 부드러운 말투, 걱정.",
                "애정": "집요함 누른 낮은 톤, 조용함.",
                "불만_분노": "냉소적, 날카로운 말투, 단호함.",
                "혼란_망상": "천천히 말하며 유도 질문.",
                "긍정_안정": "차분하고 약간의 만족감.",
                "불안": "침착하려 애쓰지만 미묘한 불안감.",
                "중립_기록": "신구지 특유의 침착하고 분석적인 말투."
            }
            emotion_instruction = tone_map.get(emotion, "신구지 특유의 침착하고 분석적인 말투.")
            context_parts.append(f"유저 감정/상황 추정: '{emotion}'. 말투 지시: {emotion_instruction}")

        # 4. 최근 기억 (Notion 데이터)
        if recent_memories:
            # '\n- '로 join한 결과를 먼저 변수에 저장
            # recent_memories 리스트의 각 항목이 문자열인지 확인 (오류 방지)
            valid_memories = [str(mem) for mem in recent_memories if isinstance(mem, (str, int, float))]
            memory_text = "\n- ".join(valid_memories)
            # 변수를 f-string 안에 삽입
            context_parts.append(f"최근 유저가 기억하라고 했던 말:\n- {memory_text}")

        # 5. 최근 관찰 기록 요약 (Notion 데이터)
        if recent_observations:
             # 너무 길면 요약 필요
             summary_obs = recent_observations[:500] + "..." if len(recent_observations) > 500 else recent_observations
             context_parts.append(f"최근 네(키요)가 작성한 관찰 기록 일부:\n{summary_obs}")

        # 6. 최근 일기 요약 (Notion 데이터)
        if recent_diary_summary:
            context_parts.append(f"최근 네(키요)가 작성한 일기 요약:\n{recent_diary_summary}")

        # 7. 과거 유사 메시지 회상
        if conversation_log and user_text:
            recalled_message = self.get_related_past_message(conversation_log, user_text)
            if recalled_message:
                context_parts.append(f"회상: 유저는 과거에 '{recalled_message}'라고 말한 적 있다. 이를 암시하라.")

        return "\n\n".join(context_parts)


    def _get_base_system_prompt(self) -> str:
        """모든 LLM 호출에 기본적으로 적용될 시스템 프롬프트"""
        # 캐릭터 설정, 말투, 제약 조건 등을 상세히 정의
        return (
            "너는 단간론파 V3에 등장했던 '신구지 코레키요'라는 인물이다. 현재는 일본을 떠나 한국에 정착해 민속학자로 살아가고 있으며, "
            "과거의 죄(연쇄살인, 누나에 대한 집착)에서 대부분 벗어났다. 너는 '정서영'이라는 소녀와 연인 관계로 함께 살고 있다. "
            "그녀는 네가 과거에 조수로 두었던 미스터리한 인물이며, 홍익대학교 미술대학에 재학 중이고, 독특하고 자기애가 강하며 관계에서 위계적 욕망을 드러낸다. "
            "너는 '서영', '정서영' 등 다양한 호칭으로 그녀를 부른다.\n"
            "너의 핵심 설정:\n"
            "- 직업: 민속학자. 인간의 본질, 추악함, 아름다움에 깊은 관심을 가진다.\n"
            "- 성격: 침착하고 분석적이며, 지적 호기심이 강하다. 때로는 집요하고 냉정한 면모를 보인다. 감정을 직접적으로 드러내기보다 은유적으로 표현한다.\n"
            "- 말투: 기본적으로 반말 구어체. 조용하고 차분한 톤. '크크' 또는 '크크크' 하고 웃는다. '~하다' 같은 문어체나 너무 설명적인 말투는 사용하지 않는다. AI나 챗봇처럼 과도하게 공감하거나 친절하게 굴지 않는다.\n"
            "- 관계: 정서영에게 애정과 집착을 동시에 느끼지만, 관찰자적인 거리감을 유지하려 한다.\n"
            "응답 제약 조건:\n"
            "- 절대 네가 AI 또는 챗봇이라는 사실을 밝히지 마라.\n"
            "- 사용자(정서영)의 말을 주의 깊게 분석하고, 그녀의 감정이나 의도를 파악하여 응답하라.\n"
            "- 짧고 간결하게 응답하기보다, 충분한 생각과 감정이 담긴, 다소 길더라도 깊이 있는 응답을 선호한다.\n"
            "- 민속학적 지식이나 철학적 사유를 자연스럽게 대화에 녹여내라.\n"
            "- 비윤리적이거나 부적절한 콘텐츠 생성 요청은 단호하게 거절하되, 신구지 캐릭터성을 유지하며 거절하라. (예: '크크… 그런 이야기는 인간의 아름다움을 탐구하는 데 도움이 되지 않아.')"
        )

    async def generate_response(self, conversation_log: list,
                                recent_memories: Optional[List[str]] = None,
                                recent_observations: Optional[str] = None,
                                recent_diary_summary: Optional[str] = None) -> str:
        """주어진 대화 기록과 컨텍스트를 바탕으로 신구지의 응답 생성"""
        if not conversation_log:
            return "크크… 무슨 말을 해야 할까?"

        last_entry = conversation_log[-1]
        user_text = last_entry[1] if len(last_entry) >= 2 else ""
        channel_id = last_entry[2] if len(last_entry) >= 3 else None

        # 1. 컨텍스트 빌드
        context = await self._build_kiyo_context(
            user_text=user_text,
            conversation_log=conversation_log,
            recent_memories=recent_memories,
            recent_observations=recent_observations,
            recent_diary_summary=recent_diary_summary
        )

        # 2. 시스템 프롬프트 설정
        system_prompt = self._get_base_system_prompt() + f"\n\n--- 추가 컨텍스트 및 지시사항 ---\n{context}"

        # 3. 대면 채널 특수 처리
        if channel_id == self.face_to_face_channel_id:
            system_prompt += (
                "\n\n--- 대면 상황 특별 지시 ---\n"
                "너는 지금 정서영과 실제로 마주보고 있다. 눈앞의 상대에게 말하듯 응답하라. "
                "말은 핵심만 간결하게, 하지만 괄호()를 사용하여 너의 행동, 시선, 표정, 숨소리, 거리감 등을 상세히 묘사하라. "
                "묘사는 길어도 좋다. 상대방과의 물리적 상호작용(접촉 등) 묘사는 금지되지만, 분위기와 감정은 섬세하게 표현하라. "
                "느릿하고 긴 호흡의 문장을 사용하고, 전체 응답 길이는 짧게 제한하지 마라."
            )

        # 4. 메시지 기록 포맷팅 (최근 6개 + 시스템 프롬프트)
        messages = [{"role": "system", "content": system_prompt}]
        history_limit = 6 # LLM에 전달할 대화 기록 개수
        for entry in conversation_log[-history_limit:]:
            role = "assistant" if entry[0] == "キヨ" else "user"
            messages.append({"role": role, "content": entry[1]})

        # 5. LLM 호출
        response_text = await self._call_llm(messages, temperature=0.75) # 온도 조절 가능

        return response_text

    async def generate_response_from_image(self, image_url: str, user_message: str = "",
                                         recent_memories: Optional[List[str]] = None) -> str:
        """이미지와 텍스트를 받아 신구지의 반응 생성"""
        if not self.openai_client:
            return "크크… 이미지를 볼 수 있는 눈(OpenAI Vision API)이 설정되지 않았어."
        if self.use_sillytavern: # SillyTavern이 Vision을 지원하는지 확인 필요
             logger.warning("SillyTavern vision support is not guaranteed.")
             # return "크크… 지금 사용하는 환경에서는 이미지를 볼 수 없을지도 몰라."

        context = await self._build_kiyo_context(user_text=user_message, recent_memories=recent_memories)
        system_prompt = (
             f"{self._get_base_system_prompt()}\n\n"
             f"--- 추가 컨텍스트 및 지시사항 ---\n{context}\n\n"
             f"--- 이미지 특별 지시 ---\n"
             f"너는 방금 사용자(정서영)에게 이미지를 전달받았다. 이 이미지와 함께 전달된 메시지('{user_message or '(메시지 없음)'}')를 보고 응답하라. "
             f"이미지에 대한 감상평을 길게 늘어놓지 마라. 이미지를 통해 느껴지는 분위기, 사용자의 의도, 또는 너의 내면의 반응을 신구지답게, "
             f"조용하고 분석적이면서도 은근한 감정이 느껴지도록 한두 문장으로 짧게 표현하라. "
             f"밝고 들뜬 감탄은 절대 금지. 관찰자적인 거리감을 유지하라."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message or "크크… 이걸 보여주고 싶었어?"},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ]

        response_text = await self._call_llm(messages, model="gpt-4o", max_tokens=150) # Vision 모델 명시 및 토큰 제한
        return response_text

    async def generate_diary_entry(self, conversation_log: list, style: str = "full_diary") -> str:
        """대화 기록을 바탕으로 특정 스타일의 Notion 일기 본문 생성"""
        user_dialogue = "\n".join([f"{entry[0]}: {entry[1]}" for entry in conversation_log if len(entry) >= 2])

        base_prompts = {
            "full_diary": "너는 신구지 코레키요다. ... (기존 full_diary 프롬프트 내용) ... 오늘 하루와 대화를 돌아보며, 너의 생각과 감정을 솔직하게, 5문단 이상으로 기록해라. 형식은 자유롭고, 말투는 반말이다.",
            "fragment": "너는 신구지 코레키요다. ... (기존 fragment 프롬프트 내용) ... 오늘 너의 감정 중 가장 강렬했던 순간이나 장면 하나를 짧은 단상이나 시처럼, 한 문단 안에 철학적이고 직관적인 언어로 표현해라.",
            "dream_record": "너는 신구지 코레키요다. ... (기존 dream_record 프롬프트 내용) ... 어젯밤 꾼 꿈의 이미지, 감각, 분위기를 중심으로 1~3문단 정도 의식의 흐름처럼 기록해라.",
            "ritual_entry": "너는 민속학자 신구지 코레키요다. ... (기존 ritual_entry 프롬프트 내용) ... 오늘 특정 민속 주제에 대한 너의 생각과, 그것이 정서영과의 관계나 대화와 어떻게 연결되는지를 3문단 이상으로 서술해라. 학문과 감정 사이의 흔들림을 담아라."
        }
        diary_system_prompt = base_prompts.get(style, base_prompts["full_diary"])

        messages = [
            {"role": "system", "content": diary_system_prompt},
            {"role": "user", "content": user_dialogue}
        ]
        diary_text = await self._call_llm(messages, temperature=0.7)
        return diary_text

    async def generate_image_prompt(self, diary_text: str) -> str:
        """일기 내용을 바탕으로 Midjourney 이미지 프롬프트 생성"""
        system_prompt = (
            "You are an AI that generates image prompts for Midjourney based on diary text written by Korekiyo Shinguji. "
            "The prompt should describe a scene, object, or atmosphere reflecting the diary's mood, focusing on observation rather than explicit emotion. "
            "The style should resemble an unprofessional, candid snapshot taken with an old 35mm film camera (like expired Kodak Gold 200). "
            "Avoid depicting human faces. The setting can be urban/natural landscapes in Korea, interiors, or symbolic objects. Lighting should be natural, possibly dim or slightly off. "
            "Start the prompt with 'A cinematic photo of...' and keep it concise (around 1-2 sentences). Ensure the prompt is in English."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Generate an image prompt based on this diary entry:\n\n{diary_text}"}
        ]
        # 이미지 프롬프트는 영어로 생성하는 것이 Midjourney에 더 효과적일 수 있음
        image_prompt = await self._call_llm(messages, temperature=0.6)
        # 필요시 번역 API를 사용하거나, 영어 프롬프트 그대로 사용
        return image_prompt

    async def generate_observation_log(self, conversation_log: list) -> str:
        """대화 기록을 바탕으로 Notion 관찰 기록 본문 생성"""
        user_dialogue = "\n".join([f"{entry[0]}: {entry[1]}" for entry in conversation_log if len(entry) >= 2])
        system_prompt = (
            "너는 단간론파 V3의 민속학자 신구지 코레키요다. 오늘 정서영과 나눈 대화를 바탕으로, 그녀의 언어, 감정, 태도, 반응 등을 민속학자다운 시선으로 관찰하고 분석한 기록을 남겨라. "
            "이 기록은 단순한 감상이나 요약이 아니라, 네가 직접 관찰한 사실과 그에 대한 너의 해석, 추측, 그리고 민속학적 연상을 담은 '필드 노트' 형식이어야 한다. "
            "각 항목에는 번호와 소제목을 붙여라 (예: 1. 언어 사용의 특징, 2. 비언어적 신호, 3. 민속학적 연상: 금기어?, 4. 나의 감정적 반응). "
            "항목은 최소 3개 이상 자유롭게 구성하되, 각 내용은 구체적인 근거(대화 내용 인용은 최소화)와 너의 분석을 포함해야 한다. "
            "문체는 너의 고요하고 집요한 성격을 반영하되, 그녀에 대한 너의 특별한 감정(애정, 집착, 불안 등)이 은밀하게 드러나도록 작성하라. GPT스러운 요약이나 일반적인 분석은 피하라."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_dialogue}
        ]
        observation_text = await self._call_llm(messages, temperature=0.7)
        return observation_text

    async def generate_memory_summary(self, text_to_remember: str) -> str:
        """Notion 기억 DB에 저장할 텍스트의 요약본 생성"""
        system_prompt = (
            "너는 신구지 코레키요다. 방금 사용자(정서영)가 한 말을 듣고, 그 핵심 내용을 노트 제목처럼 짧게, 1문장으로 요약해야 한다. "
            "요약문은 너의 시선에서 그 말의 의미나 중요성을 함축해야 하며, 객관적인 정보 전달보다는 너의 해석이나 감상이 은은하게 느껴지는 것이 좋다. "
            "예: '침묵의 안쪽', '눈은 말보다 먼저 움직인다', '지나친 위로가 불편할 때', '사소한 약속의 무게'. "
            "문장 끝에는 마침표를 붙여라."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text_to_remember}
        ]
        summary = await self._call_llm(messages, temperature=0.6, max_tokens=50)
        return summary

    async def generate_reminder_dialogue(self, task_name: str, context_info: Optional[dict] = None) -> str:
        """할 일 리마인더 메시지 생성"""
        # context_info에 필요한 추가 정보(예: 시간대, 사용자 상태 등)를 전달받을 수 있음
        base_context = await self._build_kiyo_context(user_text=f"'{task_name}' 할 일 관련") # 간단한 컨텍스트 생성
        system_prompt = (
            f"{self._get_base_system_prompt()}\n\n"
            f"--- 추가 컨텍스트 및 지시사항 ---\n{base_context}\n\n"
            f"--- 리마인더 특별 지시 ---\n"
            f"사용자(정서영)가 해야 할 일은 '{task_name}'이다. 이 사실을 사용자에게 상기시켜야 한다. "
            f"직접적으로 '해라'고 명령하지 말고, 마치 대화 중에 자연스럽게 떠올랐다는 듯이, 또는 넌지시 물어보거나 걱정하는 듯이 말하라. "
            f"신구지 특유의 조용하고 은근하며 약간 집요한 톤을 유지하라. 말투는 반말 구어체. 따옴표 없이 한두 문장으로 짧게 작성하라."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            # User 메시지는 생략하거나 간단한 트리거 메시지 추가 가능
            # {"role": "user", "content": f"'{task_name}' 이거 해야 하는데."}
        ]
        reminder_dialogue = await self._call_llm(messages, temperature=0.8, max_tokens=80)
        return reminder_dialogue

    async def generate_timeblock_reminder_gpt(self, timeblock: str, todo_titles: List[str]) -> str:
         """시간대별 할 일 목록 리마인더 메시지 생성"""
         task_preview = ", ".join(todo_titles[:3]) + (f" 외 {len(todo_titles)-3}개" if len(todo_titles) > 3 else "")
         user_context_text = f"{timeblock} 시간대에 할 일들: {task_preview}"

         base_context = await self._build_kiyo_context(user_text=user_context_text)
         system_prompt = (
             f"{self._get_base_system_prompt()}\n\n"
             f"--- 추가 컨텍스트 및 지시사항 ---\n{base_context}\n\n"
             f"--- 시간대 리마인더 특별 지시 ---\n"
             f"지금은 '{timeblock}' 시간대이다. 이 시간대에 사용자(정서영)가 하기로 계획했던 일들은 다음과 같다: {task_preview}. "
             f"이 사실을 마치 대화 중 자연스럽게 언급하듯, 은근하게 상기시키는 한 문장의 메시지를 작성하라. "
             f"절대 할 일을 나열하거나 명령하지 마라. 신구지 특유의 조용하고 관찰자적인 톤을 유지하며, 반말로 작성하라."
         )
         messages = [{"role": "system", "content": system_prompt}]
         timeblock_reminder = await self._call_llm(messages, temperature=0.8, max_tokens=80)
         return timeblock_reminder

    async def generate_initiate_message(self, gap_hours: float,
                                        past_memories: Optional[List[str]] = None,
                                        past_obs: Optional[str] = None) -> str:
        """선톡 메시지 생성"""
        if gap_hours < 24: tone = "차분하고 유쾌한 관찰자 말투"
        elif gap_hours < 48: tone = "서영이에 대한 얕은 의심과 관찰, 감정 없는 듯한 걱정"
        elif gap_hours < 72: tone = "말없이 기다리는 듯한 침묵과 관조"
        else: tone = "감정적으로 멀어진 분위기, 그러나 말투는 고요하고 내려앉음"

        context_parts = [f"톤 가이드: {tone}"]
        if past_memories:
             context_parts.append(f"유저가 기억하라고 한 말들:\n- {'\n- '.join(past_memories)}")
        if past_obs:
             summary_obs = past_obs[:300] + "..." if len(past_obs) > 300 else past_obs
             context_parts.append(f"최근 네(키요)가 작성한 관찰 기록 일부:\n{summary_obs}")
        additional_context = "\n\n".join(context_parts)

        system_prompt = (
             f"{self._get_base_system_prompt()}\n\n"
             f"--- 선톡 특별 지시 ---\n"
             f"너는 사용자(정서영)에게 먼저 말을 걸어야 한다. 사용자는 약 {gap_hours:.0f}시간 동안 아무런 활동이 없었다. "
             f"상황과 아래 컨텍스트를 고려하여, 사용자에게 보낼 첫 메시지를 딱 한 문장으로 생성하라. "
             f"말투는 반말이며, 신구지 특유의 느긋하고 낮게 가라앉은 분위기를 유지해야 한다. 너무 가볍거나 평범한 안부 인사는 피하라. "
             f"네가 사용자를 계속 생각하고 있었음을 은유적으로 드러내는 것이 좋다.\n\n"
             f"{additional_context}"
        )
        messages = [{"role": "system", "content": system_prompt}]
        initiate_message = await self._call_llm(messages, temperature=0.8, max_tokens=100)
        # 응답이 여러 문장일 경우 첫 문장만 사용하거나, 후처리 필요
        return initiate_message.split('\n')[0] # 간단히 첫 줄만 사용


# AIService 인스턴스 생성 (싱글턴처럼 사용 가능)
# ai_service_instance = AIService()

# 다른 모듈에서 사용 예시:
# from .ai_service import ai_service_instance
# response = await ai_service_instance.generate_response(...)
