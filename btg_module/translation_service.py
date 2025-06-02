# translation_service.py
import time
import random
import re
import csv
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
import os
import json # JSON 모듈 임포트

try:
    from .gemini_client import (
        GeminiClient,
        GeminiContentSafetyException,
        GeminiRateLimitException,
        GeminiApiException,
        GeminiInvalidRequestException,
        GeminiAllApiKeysExhaustedException 
    )
    from .file_handler import read_json_file, read_text_file # read_text_file도 필요할 수 있음 (스키마 파일이 일반 텍스트일 경우)
    from .logger_config import setup_logger
    from .exceptions import BtgTranslationException, BtgApiClientException
    from .chunk_service import ChunkService
    # types 모듈은 gemini_client에서 사용되므로, 여기서는 직접적인 의존성이 없을 수 있습니다.
    # 만약 이 파일 내에서 types.Part 등을 직접 사용한다면, 아래와 같이 임포트가 필요합니다.
    # from google.genai import types as genai_types 
    from .dtos import LorebookEntryDTO # 로어북 DTO 임포트
except ImportError:
    from gemini_client import (
        GeminiClient,
        GeminiContentSafetyException,
        GeminiRateLimitException,
        GeminiApiException,
        GeminiInvalidRequestException,
        GeminiAllApiKeysExhaustedException 
    )
    from file_handler import read_json_file, read_text_file
    from logger_config import setup_logger
    from exceptions import BtgTranslationException, BtgApiClientException
    from chunk_service import ChunkService
    from dtos import LorebookEntryDTO
    from google.genai import types as genai_types # Function Calling을 위해 추가
    # from google.genai import types as genai_types # Fallback import

logger = setup_logger(__name__)

def _format_lorebook_for_prompt(
    lorebook_entries: List[LorebookEntryDTO],
    max_entries: int,
    max_chars: int
) -> str:
    if not lorebook_entries:
        return "로어북 컨텍스트 없음"

    selected_entries_str = []
    current_chars = 0
    entries_count = 0

    # 중요도 높은 순, 중요도 같으면 키워드 가나다 순으로 정렬
    # isSpoiler가 True인 항목은 낮은 우선순위를 갖도록 조정 (예: 중요도를 낮춤)
    def sort_key(entry: LorebookEntryDTO):
        importance = entry.importance or 0
        if entry.isSpoiler:
            importance -= 100 # 스포일러 항목의 중요도를 크게 낮춤
        return (-importance, entry.keyword.lower())

    sorted_entries = sorted(lorebook_entries, key=sort_key)

    for entry in sorted_entries:
        if entries_count >= max_entries:
            break

        spoiler_text = "예" if entry.isSpoiler else "아니오"
        details_parts = []
        if entry.category:
            details_parts.append(f"카테고리: {entry.category}")
        details_parts.append(f"스포일러: {spoiler_text}")
        
        details_str = ", ".join(details_parts)
        # 로어북 항목의 원본 언어 정보를 프롬프트에 포함
        lang_info = f" (lang: {entry.source_language})" if entry.source_language else ""
        entry_str = f"- {entry.keyword}{lang_info}: {entry.description} ({details_str})"
        
        
        
        # 현재 항목 추가 시 최대 글자 수 초과하면 중단 (단, 최소 1개는 포함되도록)
        if current_chars + len(entry_str) > max_chars and entries_count > 0:
            break
        
        selected_entries_str.append(entry_str)
        current_chars += len(entry_str) + 1 # +1 for newline
        entries_count += 1
    
    if not selected_entries_str:
        return "로어북 컨텍스트 없음 (제한으로 인해 선택된 항목 없음)"
        
    return "\n".join(selected_entries_str)

class TranslationService:
    def __init__(self, gemini_client: GeminiClient, config: Dict[str, Any]):
        self.gemini_client = gemini_client
        self.config = config
        self.chunk_service = ChunkService()
        self.lorebook_entries_for_injection: List[LorebookEntryDTO] = [] # For new lorebook injection

        if self.config.get("enable_dynamic_lorebook_injection", False):
            self._load_lorebook_data()
            logger.info("동적 로어북 주입 활성화됨. 로어북 데이터 로드 시도.")
        else:
            logger.info("동적 로어북 주입 비활성화됨. 로어북 컨텍스트 없이 번역합니다.")

    def _load_lorebook_data(self):
        # 통합된 로어북 경로 사용
        lorebook_json_path_str = self.config.get("lorebook_json_path")
        if lorebook_json_path_str and os.path.exists(lorebook_json_path_str):
            lorebook_json_path = Path(lorebook_json_path_str)
            try:
                raw_data = read_json_file(lorebook_json_path)
                if isinstance(raw_data, list):
                    for item_dict in raw_data:
                        if isinstance(item_dict, dict) and "keyword" in item_dict and "description" in item_dict:
                            try:
                                entry = LorebookEntryDTO(
                                    keyword=item_dict.get("keyword", ""),
                                    description=item_dict.get("description", ""),
                                    category=item_dict.get("category"),
                                    importance=int(item_dict.get("importance", 0)) if item_dict.get("importance") is not None else None,
                                    sourceSegmentTextPreview=item_dict.get("sourceSegmentTextPreview"),
                                    isSpoiler=bool(item_dict.get("isSpoiler", False)),
                                    source_language=item_dict.get("source_language") # 로어북 JSON에서 source_language 로드
                                )
                                if entry.keyword and entry.description: # 필수 필드 확인
                                    self.lorebook_entries_for_injection.append(entry)
                                else:
                                    logger.warning(f"로어북 항목에 필수 필드(keyword 또는 description) 누락: {item_dict}")
                            except (TypeError, ValueError) as e_dto:
                                logger.warning(f"로어북 항목 DTO 변환 중 오류: {item_dict}, 오류: {e_dto}")
                        else:
                            logger.warning(f"잘못된 로어북 항목 형식 (딕셔너리가 아니거나 필수 키 누락): {item_dict}")
                    logger.info(f"{len(self.lorebook_entries_for_injection)}개의 로어북 항목을 로드했습니다: {lorebook_json_path}")
                else:
                    logger.error(f"로어북 JSON 파일이 리스트 형식이 아닙니다: {lorebook_json_path}, 타입: {type(raw_data)}")
            except Exception as e:
                logger.error(f"로어북 JSON 파일 처리 중 예상치 못한 오류 ({lorebook_json_path}): {e}", exc_info=True)
                self.lorebook_entries_for_injection = []
        else:
            logger.info(f"로어북 JSON 파일({lorebook_json_path_str})이 설정되지 않았거나 존재하지 않습니다. 동적 주입을 위해 로어북을 사용하지 않습니다.")
            self.lorebook_entries_for_injection = []

    def _construct_prompt(self, chunk_text: str) -> str:
        prompt_template = self.config.get("prompts", "Translate to Korean: {{slot}}")
        if isinstance(prompt_template, (list, tuple)):
            prompt_template = prompt_template[0] if prompt_template else "Translate to Korean: {{slot}}"

        final_prompt = prompt_template

        # Determine the source language for the current chunk to filter lorebook entries
        config_source_lang = self.config.get("novel_language") # 통합된 설정 사용
        # Fallback language from config, with a hardcoded default if the config key itself is missing
        config_fallback_lang = self.config.get("novel_language_fallback", "ja") # 통합된 폴백 설정 사용

        # "auto" 모드일 때, LLM이 언어를 감지하고 로어북을 필터링하도록 프롬프트가 구성됩니다.
        # Python 단에서 current_source_lang_for_translation을 확정하지 않습니다.
        # 로깅이나 특정 조건부 로직을 위해선 여전히 필요할 수 있으나, 로어북 필터링은 LLM으로 넘어갑니다.
        current_source_lang_for_lorebook_filtering: Optional[str] = None

        if config_source_lang == "auto":
            logger.info(f"번역 출발 언어 설정: 'auto'. LLM이 프롬프트 내에서 언어를 감지하고 로어북을 적용하도록 합니다.")
            # current_source_lang_for_lorebook_filtering는 None으로 유지하거나 "auto"로 설정.
            # 로어북 필터링은 LLM의 역할이 됩니다.
        elif config_source_lang and isinstance(config_source_lang, str) and config_source_lang.strip(): # Specific language code provided
            current_source_lang_for_lorebook_filtering = config_source_lang
            logger.info(f"명시적 번역 출발 언어 '{current_source_lang_for_lorebook_filtering}' 사용. 로어북도 이 언어 기준으로 필터링됩니다.")
        else: # config_source_lang is None, empty string, or not "auto"
            current_source_lang_for_lorebook_filtering = config_fallback_lang
            logger.warning(f"번역 출발 언어가 유효하게 설정되지 않았거나 'auto'가 아닙니다. 폴백 언어 '{current_source_lang_for_lorebook_filtering}'를 로어북 필터링에 사용.")

        # 1. Dynamic Lorebook Injection
        if self.config.get("enable_dynamic_lorebook_injection", False) and \
           self.lorebook_entries_for_injection and \
           "{{lorebook_context}}" in final_prompt:

            relevant_entries_for_chunk: List[LorebookEntryDTO] = []
            chunk_text_lower = chunk_text.lower() # For case-insensitive keyword matching

            if config_source_lang == "auto":
                # "auto" 모드: LLM이 언어를 감지하고 로어북을 필터링하도록 지시.
                # Python에서는 키워드 기반으로만 필터링하거나, 모든 로어북 항목을 전달.
                # 여기서는 키워드 기반 필터링만 수행하고, LLM이 언어 필터링을 하도록 프롬프트에 명시.
                logger.info("자동 언어 감지 모드: 로어북은 키워드 일치로 필터링 후 LLM에 전달. LLM이 언어 기반 추가 필터링 수행.")
                for entry in self.lorebook_entries_for_injection:
                    if entry.keyword.lower() in chunk_text_lower:
                        relevant_entries_for_chunk.append(entry)
            else:
                # 명시적 언어 설정 모드: Python에서 언어 및 키워드 기반으로 필터링.
                logger.info(f"명시적 언어 모드 ('{current_source_lang_for_lorebook_filtering}'): 로어북을 언어 및 키워드 기준으로 필터링.")
                for entry in self.lorebook_entries_for_injection:
                    # 로어북 항목의 언어와 현재 번역 출발 언어가 일치하는지 확인
                    if entry.source_language and \
                       current_source_lang_for_lorebook_filtering and \
                       entry.source_language.lower() != current_source_lang_for_lorebook_filtering.lower():
                        logger.debug(f"로어북 항목 '{entry.keyword}' 건너뜀: 언어 불일치 (로어북: {entry.source_language}, 번역 출발: {current_source_lang_for_lorebook_filtering}).")
                        continue

                    if entry.keyword.lower() in chunk_text_lower:
                        relevant_entries_for_chunk.append(entry)
            
            logger.debug(f"현재 청크에 대해 {len(relevant_entries_for_chunk)}개의 관련 로어북 항목 발견.")

            # 1.b. Format the relevant entries for the prompt
            max_entries = self.config.get("max_lorebook_entries_per_chunk_injection", 3)
            max_chars = self.config.get("max_lorebook_chars_per_chunk_injection", 500)
            
            formatted_lorebook_context = _format_lorebook_for_prompt(
                relevant_entries_for_chunk, max_entries, max_chars # Pass only relevant entries
            )
            
            # Check if actual content was formatted (not just "없음" messages)
            if formatted_lorebook_context != "로어북 컨텍스트 없음" and \
               formatted_lorebook_context != "로어북 컨텍스트 없음 (제한으로 인해 선택된 항목 없음)":
                logger.info(f"API 요청에 동적 로어북 컨텍스트 주입됨. 내용 일부: {formatted_lorebook_context[:100]}...")
                # 주입된 로어북 키워드 로깅
                injected_keywords = [entry.keyword for entry in relevant_entries_for_chunk if entry.keyword.lower() in chunk_text_lower]
                if injected_keywords:
                    logger.info(f"  🔑 주입된 로어북 키워드: {', '.join(injected_keywords)}")
            else:
                logger.debug(f"동적 로어북 주입 시도했으나, 관련 항목 없거나 제한으로 인해 실제 주입 내용 없음. 사용된 메시지: {formatted_lorebook_context}")
            final_prompt = final_prompt.replace("{{lorebook_context}}", formatted_lorebook_context)
        else:
            if "{{lorebook_context}}" in final_prompt:
                 final_prompt = final_prompt.replace("{{lorebook_context}}", "로어북 컨텍스트 없음 (주입 비활성화 또는 해당 항목 없음)")
                 logger.debug("동적 로어북 주입 비활성화 또는 플레이스홀더 부재로 '컨텍스트 없음' 메시지 사용.")
        
        # 3. Main content slot - This should be done *after* all other placeholders are processed.
        final_prompt = final_prompt.replace("{{slot}}", chunk_text)
        
        return final_prompt

    def translate_text(self, text_chunk: str) -> str:
        """기존 translate_text 메서드 (수정 없음)"""
        if not text_chunk.strip():
            return ""

        processed_text = text_chunk
        prompt = self._construct_prompt(processed_text)

        try:
            logger.debug(f"Gemini API 호출 시작. 모델: {self.config.get('model_name')}")
            
            translated_text = self.gemini_client.generate_text(
                prompt=prompt,
                model_name=self.config.get("model_name", "gemini-2.0-flash"),
                generation_config_dict={
                    "temperature": self.config.get("temperature", 0.7),
                    "top_p": self.config.get("top_p", 0.9)
                },
            )

            if translated_text is None:
                logger.error("GeminiClient.generate_text가 None을 반환했습니다.")
                raise BtgApiClientException("API 호출 결과가 없습니다.")

            logger.debug(f"Gemini API 호출 성공. 번역된 텍스트 (일부): {translated_text[:100]}...")

        except GeminiContentSafetyException as e_safety:
            logger.warning(f"콘텐츠 안전 문제로 번역 실패: {e_safety}")
            raise BtgTranslationException(f"콘텐츠 안전 문제로 번역할 수 없습니다. ({e_safety})", original_exception=e_safety) from e_safety
        except GeminiAllApiKeysExhaustedException as e_keys:
            logger.error(f"API 키 회전 실패: 모든 API 키 소진 또는 유효하지 않음. 원본 오류: {e_keys}")
            raise BtgApiClientException(f"모든 API 키를 사용했으나 요청에 실패했습니다. API 키 설정을 확인하세요. ({e_keys})", original_exception=e_keys) from e_keys
        except GeminiRateLimitException as e_rate:
            logger.error(f"API 사용량 제한 초과 (키 회전 후에도 발생): {e_rate}")
            raise BtgApiClientException(f"API 사용량 제한을 초과했습니다. 잠시 후 다시 시도해주세요. ({e_rate})", original_exception=e_rate) from e_rate
        except GeminiInvalidRequestException as e_invalid:
            logger.error(f"잘못된 API 요청: {e_invalid}")
            raise BtgApiClientException(f"잘못된 API 요청입니다: {e_invalid}", original_exception=e_invalid) from e_invalid
        # 중복된 GeminiContentSafetyException 제거
        except GeminiApiException as e_api:
            logger.error(f"Gemini API 호출 중 일반 오류 발생: {e_api}")
            raise BtgApiClientException(f"API 호출 중 오류가 발생했습니다: {e_api}", original_exception=e_api) from e_api
        except Exception as e:
            logger.error(f"번역 중 예상치 못한 오류 발생: {e}", exc_info=True)
            raise BtgTranslationException(f"번역 중 알 수 없는 오류가 발생했습니다: {e}", original_exception=e) from e
        
        final_text = translated_text 
        return final_text.strip()
    
    def _load_response_schema(self, schema_name: str) -> Optional[Dict[str, Any]]:
        """
        지정된 이름의 응답 스키마 JSON 파일을 로드합니다.
        스키마 파일은 설정된 'response_schemas_dir' 디렉토리에서 찾습니다.
        """
        schemas_dir_path_str = self.config.get("response_schemas_dir")
        if not schemas_dir_path_str:
            logger.warning("응답 스키마 디렉토리('response_schemas_dir')가 설정되지 않았습니다. 스키마를 로드할 수 없습니다.")
            return None
        
        schema_file_path = Path(schemas_dir_path_str) / (schema_name if schema_name.endswith(".json") else f"{schema_name}.json")
        
        if not schema_file_path.exists() or not schema_file_path.is_file():
            logger.warning(f"응답 스키마 파일을 찾을 수 없습니다: '{schema_file_path}'")
            return None
        
        try:
            # file_handler.read_json_file은 이미 JSON 파싱을 수행합니다.
            schema_content = read_json_file(schema_file_path)
            if not isinstance(schema_content, dict): # 스키마는 보통 dict 형태
                logger.error(f"로드된 스키마 '{schema_name}'의 내용이 JSON 객체(dict)가 아닙니다. 타입: {type(schema_content)}")
                return None
            logger.info(f"응답 스키마 '{schema_name}'을(를) '{schema_file_path}'에서 성공적으로 로드했습니다.")
            return schema_content
        except json.JSONDecodeError as e_json:
            logger.error(f"응답 스키마 파일 '{schema_file_path}' 파싱 중 JSON 오류 발생: {e_json}")
            return None
        except Exception as e:
            logger.error(f"응답 스키마 파일 '{schema_file_path}' 로드 중 예상치 못한 오류 발생: {e}", exc_info=True)
            return None

    def request_structured_reconstruction(
        self,
        primary_translated_text: str,
        original_html_structure_info: Any,
        response_schema_name: str,
        generation_config_overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Phase 3 (2단계 파이프라인): 1차 번역된 텍스트와 원본 HTML 구조 정보를 바탕으로
        Gemini API에 구조화된 재구성을 요청합니다.
        """
        if not self.gemini_client:
            raise BtgTranslationException("GeminiClient가 초기화되지 않아 구조화된 재구성을 요청할 수 없습니다.")

        json_schema_definition = self._load_response_schema(response_schema_name)
        if not json_schema_definition:
            logger.warning(f"스키마 '{response_schema_name}' 로드 실패. 스키마 없이 진행하거나 오류 처리 필요.")
            # 필요시 여기서 예외 발생: raise BtgConfigException(f"응답 스키마 '{response_schema_name}'을 로드할 수 없습니다.")

        # 프롬프트 구성
        prompt = f"""
        다음은 1차 번역된 텍스트와 원본 HTML 구조 정보입니다.
        이 정보들을 바탕으로 콘텐츠를 재구성하여, 아래 명시된 JSON 스키마에 따라 응답해주세요.

        JSON 스키마:
        ```json
        {json.dumps(json_schema_definition, indent=2, ensure_ascii=False) if json_schema_definition else "제공된 스키마 없음. 일반적인 구조화된 JSON으로 응답해주세요."}
        ```

        1차 번역된 텍스트:
        ---
        {primary_translated_text}
        ---

        원본 HTML 구조 정보:
        ---
        {json.dumps(original_html_structure_info, indent=2, ensure_ascii=False) if isinstance(original_html_structure_info, (dict, list)) else str(original_html_structure_info)}
        ---

        요청: 위의 정보를 사용하여 콘텐츠를 재구성하고, 명시된 JSON 스키마에 맞는 JSON 객체로만 응답해주세요.
        다른 설명이나 추가 텍스트 없이 JSON 객체만 반환해야 합니다.
        """

        effective_gen_config = {
            "temperature": self.config.get("temperature", 0.3), # 구조화 작업에는 낮은 온도가 적합할 수 있음
            "top_p": self.config.get("top_p", 0.9),
            "response_mime_type": "application/json" # JSON 응답 요청
        }
        if generation_config_overrides:
            effective_gen_config.update(generation_config_overrides)

        try:
            logger.info(f"구조화된 재구성 요청 시작 (스키마: {response_schema_name}).")
            response_data = self.gemini_client.generate_text(
                prompt=prompt,
                model_name=self.config.get("model_name", "gemini-1.5-flash-latest"),
                generation_config_dict=effective_gen_config
            )
            if isinstance(response_data, dict):
                return response_data
            elif isinstance(response_data, str): # GeminiClient가 JSON 파싱에 실패한 경우
                logger.warning("GeminiClient가 JSON 문자열을 반환했습니다 (파싱 실패 또는 API가 JSON 아닌 응답). 재파싱 시도.")
                try:
                    return json.loads(response_data)
                except json.JSONDecodeError as e_json_reparse:
                    raise BtgTranslationException(f"구조화된 재구성 응답 파싱 실패: {e_json_reparse}. 응답: {response_data[:200]}...", original_exception=e_json_reparse)
            else:
                raise BtgTranslationException(f"구조화된 재구성 요청에 대한 예상치 않은 응답 타입: {type(response_data)}")
        except (BtgApiClientException, GeminiAllApiKeysExhaustedException) as e_api:
            logger.error(f"구조화된 재구성 중 API 오류: {e_api}", exc_info=True)
            raise # BtgIntegrationService에서 처리하도록 그대로 전달
        except Exception as e:
            logger.error(f"구조화된 재구성 중 예상치 못한 오류: {e}", exc_info=True)
            raise BtgTranslationException(f"구조화된 재구성 중 오류 발생: {e}", original_exception=e) from e

    def request_direct_structured_translation(
        self,
        content_to_translate: str,
        source_lang: str,
        target_lang: str,
        response_schema_name: str,
        generation_config_overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Phase 3 (제한적 구조화 출력): 특정 콘텐츠에 대해 직접 구조화된 번역 출력을 요청합니다.
        """
        if not self.gemini_client:
            raise BtgTranslationException("GeminiClient가 초기화되지 않아 직접 구조화된 번역을 요청할 수 없습니다.")

        json_schema_definition = self._load_response_schema(response_schema_name)
        # 스키마 로드 실패 시 처리 (위와 유사)
        if not json_schema_definition:
            logger.warning(f"스키마 '{response_schema_name}' 로드 실패. 스키마 없이 진행하거나 오류 처리 필요.")

        prompt = f"""
        다음 텍스트를 {source_lang}에서 {target_lang}(으)로 번역하고, 결과를 아래 명시된 JSON 스키마에 따라 구조화해주세요.

        JSON 스키마:
        ```json
        {json.dumps(json_schema_definition, indent=2, ensure_ascii=False) if json_schema_definition else "제공된 스키마 없음. 일반적인 구조화된 JSON으로 응답해주세요."}
        ```

        번역 및 구조화할 원본 텍스트 ({source_lang}):
        ---
        {content_to_translate}
        ---

        요청: 위의 텍스트를 {target_lang}(으)로 번역하고, 그 결과를 명시된 JSON 스키마에 맞는 JSON 객체로만 응답해주세요.
        다른 설명이나 추가 텍스트 없이 JSON 객체만 반환해야 합니다.
        """

        effective_gen_config = {
            "temperature": self.config.get("temperature", 0.5), # 번역과 구조화를 동시에 하므로 약간의 유연성
            "top_p": self.config.get("top_p", 0.9),
            "response_mime_type": "application/json"
        }
        if generation_config_overrides:
            effective_gen_config.update(generation_config_overrides)

        try:
            logger.info(f"직접 구조화 번역 요청 시작 (스키마: {response_schema_name}, {source_lang} -> {target_lang}).")
            response_data = self.gemini_client.generate_text(
                prompt=prompt,
                model_name=self.config.get("model_name", "gemini-1.5-flash-latest"),
                generation_config_dict=effective_gen_config
            )
            if isinstance(response_data, dict):
                return response_data
            elif isinstance(response_data, str):
                logger.warning("GeminiClient가 JSON 문자열을 반환했습니다 (직접 구조화 번역). 재파싱 시도.")
                try:
                    return json.loads(response_data)
                except json.JSONDecodeError as e_json_reparse:
                    raise BtgTranslationException(f"직접 구조화 번역 응답 파싱 실패: {e_json_reparse}. 응답: {response_data[:200]}...", original_exception=e_json_reparse)
            else:
                raise BtgTranslationException(f"직접 구조화 번역 요청에 대한 예상치 않은 응답 타입: {type(response_data)}")
        except (BtgApiClientException, GeminiAllApiKeysExhaustedException) as e_api:
            logger.error(f"직접 구조화 번역 중 API 오류: {e_api}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"직접 구조화 번역 중 예상치 못한 오류: {e}", exc_info=True)
            raise BtgTranslationException(f"직접 구조화 번역 중 오류 발생: {e}", original_exception=e) from e

    def translate_text_with_content_safety_retry(
        self, 
        text_chunk: str, 
        max_split_attempts: int = 3,
        min_chunk_size: int = 100
    ) -> str:
        """
        콘텐츠 안전 오류 발생시 청크를 분할하여 재시도하는 번역 메서드
        
        Args:
            text_chunk: 번역할 텍스트
            max_split_attempts: 최대 분할 시도 횟수
            min_chunk_size: 최소 청크 크기
            
        Returns:
            번역된 텍스트 (실패한 부분은 오류 메시지로 대체)
        """
        try:
            # 1차 시도: 전체 청크 번역
            return self.translate_text(text_chunk)
            
        except BtgTranslationException as e:
            # 검열 오류가 아닌 경우 그대로 예외 발생
            if "콘텐츠 안전 문제" not in str(e):
                raise e
            
            logger.warning(f"콘텐츠 안전 문제 감지. 청크 분할 재시도 시작: {str(e)}")
            return self._translate_with_recursive_splitting(
                text_chunk, max_split_attempts, min_chunk_size, current_attempt=1
            )

    def _translate_with_recursive_splitting(
        self,
        text_chunk: str,
        max_split_attempts: int,
        min_chunk_size: int,
        current_attempt: int = 1
    ) -> str:
    
        if current_attempt > max_split_attempts:
            logger.error(f"최대 분할 시도 횟수({max_split_attempts})에 도달. 번역 실패.")
            return f"[검열로 인한 번역 실패: 최대 분할 시도 초과]"

        if len(text_chunk.strip()) <= min_chunk_size:
            logger.warning(f"최소 청크 크기에 도달했지만 여전히 검열됨: {text_chunk[:50]}...")
            return f"[검열로 인한 번역 실패: {text_chunk[:30]}...]"

        logger.info(f"📊 청크 분할 시도 #{current_attempt} (깊이: {current_attempt-1})")
        logger.info(f"   📏 원본 크기: {len(text_chunk)} 글자")
        logger.info(f"   🎯 목표 크기: {len(text_chunk) // 2} 글자")
        logger.info(f"   📝 내용 미리보기: {text_chunk[:100].replace(chr(10), ' ')}...")

        
        # 1단계: 크기 기반 분할
        sub_chunks = self.chunk_service.split_chunk_recursively(
            text_chunk,
            target_size=len(text_chunk) // 2,
            min_chunk_size=min_chunk_size,
            max_split_depth=1,  # 1단계만 분할
            current_depth=0
        )
        
        # 분할이 안된 경우 문장 기반 분할 시도
        if len(sub_chunks) <= 1:
            logger.info("크기 기반 분할 실패. 문장 기반 분할 시도.")
            sub_chunks = self.chunk_service.split_chunk_by_sentences(
                text_chunk, max_sentences_per_chunk=1
            )
        
        if len(sub_chunks) <= 1:
            logger.error("청크 분할 실패. 번역 포기.")
            return f"[분할 불가능한 검열 콘텐츠: {text_chunk[:30]}...]"
        
        # 각 서브 청크 개별 번역 시도
        translated_parts = []
        total_sub_chunks = len(sub_chunks)
        successful_sub_chunks = 0
        failed_sub_chunks = 0
        
        logger.info(f"🔄 분할 완료: {total_sub_chunks}개 서브 청크 생성")
        
        for i, sub_chunk in enumerate(sub_chunks):
            sub_chunk_info = f"서브 청크 {i+1}/{total_sub_chunks}"
            sub_chunk_size = len(sub_chunk.strip())
            sub_chunk_preview = sub_chunk.strip()[:50].replace('\n', ' ') + '...'
            
            logger.info(f"   🚀 {sub_chunk_info} 번역 시작")
            logger.debug(f"      📏 크기: {sub_chunk_size} 글자")
            logger.debug(f"      📝 내용: {sub_chunk_preview}")
            
            start_time = time.time()
            
            try:
                translated_part = self.translate_text(sub_chunk.strip())
                processing_time = time.time() - start_time
                
                translated_parts.append(translated_part)
                successful_sub_chunks += 1
                
                logger.info(f"   ✅ {sub_chunk_info} 번역 성공 (소요: {processing_time:.2f}초)")
                logger.debug(f"      📊 결과 길이: {len(translated_part)} 글자")
                logger.debug(f"      📈 진행률: {(i+1)/total_sub_chunks*100:.1f}% ({i+1}/{total_sub_chunks})")
                
            except BtgTranslationException as sub_e:
                processing_time = time.time() - start_time
                
                if "콘텐츠 안전 문제" in str(sub_e):
                    logger.warning(f"   🛡️ {sub_chunk_info} 검열 발생 (소요: {processing_time:.2f}초)")
                    logger.info(f"   🔄 재귀 분할 시도 (깊이: {current_attempt} → {current_attempt+1})")
                    
                    # 재귀적으로 더 작게 분할 시도
                    recursive_result = self._translate_with_recursive_splitting(
                        sub_chunk, max_split_attempts, min_chunk_size, current_attempt + 1
                    )
                    translated_parts.append(recursive_result)
                    
                    if "[검열로 인한 번역 실패" in recursive_result:
                        failed_sub_chunks += 1
                        logger.warning(f"   ❌ {sub_chunk_info} 최종 실패")
                    else:
                        successful_sub_chunks += 1
                        logger.info(f"   ✅ {sub_chunk_info} 재귀 분할 후 성공")
                else:
                    # 다른 번역 오류인 경우
                    failed_sub_chunks += 1
                    logger.error(f"   ❌ {sub_chunk_info} 번역 실패 (소요: {processing_time:.2f}초): {sub_e}")
                    translated_parts.append(f"[번역 실패: {str(sub_e)}]")
                
                logger.debug(f"      📈 진행률: {(i+1)/total_sub_chunks*100:.1f}% ({i+1}/{total_sub_chunks})")

        
        # 번역된 부분들을 결합
        final_result = " ".join(translated_parts)
        
        # 분할 번역 완료 요약
        logger.info(f"📋 분할 번역 완료 요약 (깊이: {current_attempt-1})")
        logger.info(f"   📊 총 서브 청크: {total_sub_chunks}개")
        logger.info(f"   ✅ 성공: {successful_sub_chunks}개")
        logger.info(f"   ❌ 실패: {failed_sub_chunks}개")
        logger.info(f"   📏 최종 결과 길이: {len(final_result)} 글자")
        
        if successful_sub_chunks > 0:
            success_rate = (successful_sub_chunks / total_sub_chunks) * 100
            logger.info(f"   📈 성공률: {success_rate:.1f}%")
        
        return final_result
    




if __name__ == '__main__':
    # MockGeminiClient에서 types를 사용하므로, 이 블록 내에서 임포트합니다.
    from google.genai import types as genai_types # Ensure types is imported for hints
    
    print("--- TranslationService 테스트 ---")
    class MockGeminiClient(GeminiClient):
        def __init__(self, auth_credentials, project=None, location=None, requests_per_minute: Optional[int] = None):
            try:
                super().__init__(auth_credentials=auth_credentials, project=project, location=location, requests_per_minute=requests_per_minute)
            except Exception as e:
                print(f"Warning: MockGeminiClient super().__init__ failed: {e}. This might be okay for some mock scenarios.")
                # If super init fails (e.g. dummy API key validation),
                # the mock might still function if it overrides all necessary methods
                # and doesn't rely on base class state initialized by __init__.
                # For Pylance, inheritance is the main fix.

            self.mock_auth_credentials = auth_credentials
            self.current_model_name_for_test: Optional[str] = None
            self.mock_api_keys_list: List[str] = []
            self.mock_current_api_key: Optional[str] = None

            if isinstance(auth_credentials, list):
                self.mock_api_keys_list = auth_credentials
                if self.mock_api_keys_list: self.mock_current_api_key = self.mock_api_keys_list[0]
            elif isinstance(auth_credentials, str) and not auth_credentials.startswith('{'): # Assuming API key string
                self.mock_api_keys_list = [auth_credentials]
                self.mock_current_api_key = auth_credentials
            print(f"MockGeminiClient initialized. Mock API Keys: {self.mock_api_keys_list}, Mock Current Key: {self.mock_current_api_key}")

        def generate_text(
            self,
            prompt: Union[str, List[Union[str, genai_types.Part]]],
            model_name: str,
            generation_config_dict: Optional[Dict[str, Any]] = None,
            safety_settings_list_of_dicts: Optional[List[Dict[str, Any]]] = None,
            system_instruction_text: Optional[str] = None,
            max_retries: int = 5,
            initial_backoff: float = 2.0,
            max_backoff: float = 60.0,
            stream: bool = False
        ) -> Optional[Union[str, Any]]:
            self.current_model_name_for_test = model_name

            prompt_text_for_mock = ""
            if isinstance(prompt, str):
                prompt_text_for_mock = prompt
            elif isinstance(prompt, list):
                temp_parts = []
                for item in prompt:
                    if isinstance(item, str):
                        temp_parts.append(item)
                    elif hasattr(item, 'text'): # Duck typing for Part-like objects
                        temp_parts.append(item.text)
                    else:
                        temp_parts.append(str(item))
                prompt_text_for_mock = "".join(temp_parts)

            print(f"  MockGeminiClient.generate_text 호출됨 (모델: {model_name}). Mock 현재 키: {self.mock_current_api_key[:5] if self.mock_current_api_key else 'N/A'}")

            if "안전 문제" in prompt_text_for_mock:
                raise GeminiContentSafetyException("Mock 콘텐츠 안전 문제")
            if "사용량 제한" in prompt_text_for_mock: # Simplified logic for mock
                raise GeminiRateLimitException("Mock API 사용량 제한")
            if "잘못된 요청" in prompt_text_for_mock:
                raise GeminiInvalidRequestException("Mock 잘못된 요청")

            text_to_be_translated = prompt_text_for_mock
            if "번역할 텍스트:\n" in prompt_text_for_mock:
                text_to_be_translated = prompt_text_for_mock.split("번역할 텍스트:\n")[-1].strip()
            elif "Translate to Korean:" in prompt_text_for_mock:
                 text_to_be_translated = prompt_text_for_mock.split("Translate to Korean:")[-1].strip()

            mock_translation = f"[번역됨] {text_to_be_translated[:50]}..."

            is_json_response_expected = generation_config_dict and \
                                        generation_config_dict.get("response_mime_type") == "application/json"

            if is_json_response_expected:
                return {"translated_text": mock_translation, "mock_json": True}
            else:
                return mock_translation

        def list_models(self) -> List[Dict[str, Any]]:
            print("  MockGeminiClient.list_models 호출됨")
            # Return a structure similar to what GeminiClient.list_models would return
            return [
                {"name": "models/mock-gemini-flash", "short_name": "mock-gemini-flash", "display_name": "Mock Gemini Flash", "description": "A mock flash model.", "input_token_limit": 1000, "output_token_limit": 1000},
                {"name": "models/mock-gemini-pro", "short_name": "mock-gemini-pro", "display_name": "Mock Gemini Pro", "description": "A mock pro model.", "input_token_limit": 2000, "output_token_limit": 2000},
            ]

    sample_config_base = {
        "model_name": "gemini-1.5-flash", "temperature": 0.7, "top_p": 0.9,
        "prompts": "다음 텍스트를 한국어로 번역해주세요. 로어북 컨텍스트: {{lorebook_context}}\n\n번역할 텍스트:\n{{slot}}",
        "enable_dynamic_lorebook_injection": True, # 테스트를 위해 활성화
        "lorebook_json_path": "test_lorebook.json", # 통합된 로어북 경로
        "max_lorebook_entries_per_chunk_injection": 3,
        "max_lorebook_chars_per_chunk_injection": 200,
    }

    # 1. 로어북 주입 테스트
    print("\n--- 1. 로어북 주입 번역 테스트 ---")
    config1 = sample_config_base.copy()
    
    # 테스트용 로어북 파일 생성
    test_lorebook_data = [
        {"keyword": "Alice", "description": "주인공 앨리스", "category": "인물", "importance": 10, "isSpoiler": False},
        {"keyword": "Bob", "description": "앨리스의 친구 밥", "category": "인물", "importance": 8, "isSpoiler": False}
    ]
    from file_handler import write_json_file, delete_file # write_csv_file -> write_json_file
    test_lorebook_file = Path("test_lorebook.json")
    if test_lorebook_file.exists(): delete_file(test_lorebook_file)
    write_json_file(test_lorebook_file, test_lorebook_data)

    gemini_client_instance = MockGeminiClient(auth_credentials="dummy_api_key")
    translation_service1 = TranslationService(gemini_client_instance, config1)
    text_to_translate1 = "Hello Alice, how are you Bob?"
    try:
        translated1 = translation_service1.translate_text(text_to_translate1)
        print(f"원본: {text_to_translate1}")
        print(f"번역 결과: {translated1}")
    except Exception as e:
        print(f"테스트 1 오류: {e}")
    finally:
        if test_lorebook_file.exists(): delete_file(test_lorebook_file)

    # 2. 로어북 비활성화 테스트
    print("\n--- 2. 로어북 비활성화 테스트 ---")
    config2 = sample_config_base.copy()
    config2["enable_dynamic_lorebook_injection"] = False
    translation_service2 = TranslationService(gemini_client_instance, config2)
    text_to_translate2 = "This is a test sentence."
    try:
        translated2 = translation_service2.translate_text(text_to_translate2)
        print(f"원본: {text_to_translate2}")
        print(f"번역 결과: {translated2}")
    except Exception as e:
        print(f"테스트 2 오류: {e}")

    # 3. 콘텐츠 안전 문제 테스트
    print("\n--- 3. 콘텐츠 안전 문제 테스트 ---")
    config3 = sample_config_base.copy()
    translation_service3 = TranslationService(gemini_client_instance, config3)
    text_unsafe = "안전 문제 테스트용 텍스트"
    try:
        translation_service3.translate_text(text_unsafe)
    except BtgTranslationException as e:
        print(f"예상된 예외 발생 (콘텐츠 안전): {e}")
    except Exception as e:
        print(f"테스트 3 오류: {type(e).__name__} - {e}")

    print("\n--- TranslationService 테스트 종료 ---")
