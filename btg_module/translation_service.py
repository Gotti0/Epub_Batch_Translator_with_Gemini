# translation_service.py
import time
import random
import re
import csv
import json # For formatting content_items in prompt
from pathlib import Path # Added import for Path
from typing import List, Dict, Any, Optional, Union # Union 추가 # type: ignore

import os

try:
    from .gemini_client import (
        GeminiClient,
        GeminiContentSafetyException,
        GeminiRateLimitException,
        GeminiApiException,
        GeminiInvalidRequestException,
        GeminiAllApiKeysExhaustedException 
    )
    from .file_handler import read_json_file # Not directly used in new method
    from .logger_config import setup_logger
    from .exceptions import BtgTranslationException, BtgApiClientException, BtgServiceException # Added BtgServiceException
    from .chunk_service import ChunkService
    # types 모듈은 gemini_client에서 사용되므로, 여기서는 직접적인 의존성이 없을 수 있습니다.
    # 만약 이 파일 내에서 types.Part 등을 직접 사용한다면, 아래와 같이 임포트가 필요합니다.
    # from google.genai import types as genai_types 
    from .dtos import LorebookEntryDTO # 로어북 DTO 임포트
except ImportError:
    from .gemini_client import ( # Fallback to relative
        GeminiClient,
        GeminiContentSafetyException,
        GeminiRateLimitException,
        GeminiApiException,
        GeminiInvalidRequestException,
        GeminiAllApiKeysExhaustedException 
    )
    from .file_handler import read_json_file # Fallback to relative
    from .logger_config import setup_logger # Fallback to relative
    from .exceptions import BtgTranslationException, BtgApiClientException, BtgServiceException # Fallback to relative
    from .chunk_service import ChunkService # Fallback to relative
    from .dtos import LorebookEntryDTO # Fallback to relative
    # from google.genai import types as genai_types # Fallback import

logger = setup_logger(__name__)

# _format_lorebook_for_prompt and existing _construct_prompt, translate_text, etc. remain for plain text translation.

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
        
        # EBTG가 BTG를 사용할 때는 EBTG가 로어북 컨텍스트를 관리하므로,
        # BTG 자체의 로어북 로딩은 lorebook_json_path가 있고,
        # enable_dynamic_lorebook_injection이 True일 때만 수행합니다.
        # EBTG는 BTG AppService의 config를 업데이트할 때 enable_dynamic_lorebook_injection을
        # EBTG의 설정에 따라 (또는 EBTG가 로어북을 직접 주입할 때는 False로) 설정할 수 있습니다.
        if self.config.get("lorebook_json_path") and self.config.get("enable_dynamic_lorebook_injection", False):
            self._load_lorebook_data()
            logger.info("BTG TranslationService: 동적 로어북 주입 활성화 및 경로 유효. 로어북 데이터 로드 시도.")
        else:
            logger.info("BTG TranslationService: 동적 로어북 주입 비활성화 또는 경로 없음. BTG 자체 로어북 컨텍스트 없이 번역합니다.")

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

    def _construct_prompt(self, chunk_text: str, prompt_template_str: str) -> str:
        final_prompt = prompt_template_str

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

        # 1. Dynamic Lorebook Injection (BTG 자체 로직)
        # EBTG에서 이미 {{lorebook_context}}를 채워넣었다면, 이 로직은 실행되지 않거나,
        # 플레이스홀더가 없으므로 formatted_lorebook_context가 사용되지 않습니다.
        if "{{lorebook_context}}" in final_prompt: # 플레이스홀더가 있을 때만 BTG 자체 로어북 주입 시도
            if self.config.get("enable_dynamic_lorebook_injection", False) and self.lorebook_entries_for_injection:
                relevant_entries_for_chunk: List[LorebookEntryDTO] = []
                chunk_text_lower = chunk_text.lower() # For case-insensitive keyword matching

                if config_source_lang == "auto":
                    logger.info("BTG: 자동 언어 감지 모드. 로어북은 키워드 일치로 필터링 후 LLM에 전달. LLM이 언어 기반 추가 필터링 수행.")
                    for entry in self.lorebook_entries_for_injection:
                        if entry.keyword.lower() in chunk_text_lower:
                            relevant_entries_for_chunk.append(entry)
                else:
                    logger.info(f"BTG: 명시적 언어 모드 ('{current_source_lang_for_lorebook_filtering}'). 로어북을 언어 및 키워드 기준으로 필터링.")
                    for entry in self.lorebook_entries_for_injection:
                        if entry.source_language and \
                           current_source_lang_for_lorebook_filtering and \
                           entry.source_language.lower() != current_source_lang_for_lorebook_filtering.lower():
                            logger.debug(f"BTG: 로어북 항목 '{entry.keyword}' 건너뜀: 언어 불일치 (로어북: {entry.source_language}, 번역 출발: {current_source_lang_for_lorebook_filtering}).")
                            continue
                        if entry.keyword.lower() in chunk_text_lower:
                            relevant_entries_for_chunk.append(entry)
                
                logger.debug(f"BTG: 현재 청크에 대해 {len(relevant_entries_for_chunk)}개의 관련 로어북 항목 발견.")

                max_entries = self.config.get("max_lorebook_entries_per_chunk_injection", 3)
                max_chars = self.config.get("max_lorebook_chars_per_chunk_injection", 500)
                
                formatted_lorebook_context = _format_lorebook_for_prompt(
                    relevant_entries_for_chunk, max_entries, max_chars
                )
                
                if formatted_lorebook_context != "로어북 컨텍스트 없음" and \
                   formatted_lorebook_context != "로어북 컨텍스트 없음 (제한으로 인해 선택된 항목 없음)":
                    logger.info(f"BTG: API 요청에 동적 로어북 컨텍스트 주입됨. 내용 일부: {formatted_lorebook_context[:100]}...")
                    injected_keywords = [entry.keyword for entry in relevant_entries_for_chunk if entry.keyword.lower() in chunk_text_lower]
                    if injected_keywords: logger.info(f"  🔑 BTG 주입 키워드: {', '.join(injected_keywords)}")
                else:
                    logger.debug(f"BTG: 동적 로어북 주입 시도했으나, 관련 항목 없거나 제한으로 실제 주입 내용 없음. 사용된 메시지: {formatted_lorebook_context}")
                final_prompt = final_prompt.replace("{{lorebook_context}}", formatted_lorebook_context)
            else:
                final_prompt = final_prompt.replace("{{lorebook_context}}", "로어북 컨텍스트 없음 (BTG 주입 비활성화 또는 해당 항목 없음)")
                logger.debug("BTG: 동적 로어북 주입 비활성화 또는 플레이스홀더 부재로 '컨텍스트 없음' 메시지 사용.")
        
        # 3. Main content slot - This should be done *after* all other placeholders are processed.
        final_prompt = final_prompt.replace("{{slot}}", chunk_text)
        
        return final_prompt

    def translate_text(self, text_chunk: str, prompt_template: Optional[str] = None) -> str:
        if not text_chunk.strip():
            return ""
        
        current_prompt_template = prompt_template
        if current_prompt_template is None:
            logger.warning("translate_text 호출 시 prompt_template이 제공되지 않았습니다. BTG 설정의 'universal_translation_prompt'를 사용합니다.")
            current_prompt_template = self.config.get(
                "universal_translation_prompt", 
                # BTG 자체 실행 시 사용할 매우 기본적인 폴백 프롬프트
                "Translate to {target_language}. Lorebook: {{lorebook_context}}\n\nText: {{slot}}" 
            )
            # EBTG에서 호출 시에는 {target_language}가 이미 채워진 universal_translation_prompt가 전달될 것으로 예상.
            # BTG 단독 실행 시에는 {target_language}가 남아있을 수 있으므로, BTG config의 target_language로 채움.
            if "{target_language}" in current_prompt_template:
                target_lang_for_prompt = self.config.get("target_language", "ko") 
                current_prompt_template = current_prompt_template.replace("{target_language}", target_lang_for_prompt)
                logger.debug(f"BTG translate_text: prompt_template에 {{target_language}}가 있어 '{target_lang_for_prompt}'로 대체.")

        # _construct_prompt는 {{lorebook_context}}와 {{slot}}을 채웁니다.
        processed_text = text_chunk
        prompt = self._construct_prompt(processed_text, current_prompt_template)

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
    
    def translate_text_to_xhtml_fragment(
        self,
        text_chunk: str,
        target_language: str, # 프롬프트에 이미 포함되어 있을 수 있지만, 명시적으로 받음
        prompt_template_with_context_and_slot: str # {{slot}} 플레이스홀더를 포함한 전체 프롬프트
    ) -> str:
        """
        주어진 텍스트 청크를 번역하고, 지정된 프롬프트 템플릿을 사용하여
        번역 결과를 XHTML 조각(예: <p>태그)으로 감싸 반환합니다.
        Gemini API에 JSON 응답을 요청하고, 스키마를 사용하여 특정 필드를 추출합니다.

        Args:
            text_chunk: 번역할 텍스트 조각.
            target_language: 번역 목표 언어 (프롬프트 템플릿 내 {target_language} 대체용,
                                     BtgIntegrationService에서 이미 처리했을 수 있음).
            prompt_template_with_context_and_slot: EBTG 로어북 컨텍스트와 대상 언어가 이미 채워져 있고,
                                                   {{slot}} 플레이스홀더만 남은 프롬프트 템플릿.

        Returns:
            번역되고 XHTML 조각으로 감싸진 문자열.

        Raises:
            BtgTranslationException: 번역 또는 XHTML 조각 생성 실패 시.
            BtgApiClientException: Gemini API 호출 관련 문제 발생 시.
        """
        if not self.gemini_client:
            logger.error("GeminiClient가 초기화되지 않았습니다. 텍스트를 XHTML 조각으로 번역할 수 없습니다.")
            raise BtgServiceException("GeminiClient is not initialized.")
        
        if not text_chunk.strip():
            logger.info("번역할 텍스트 청크가 비어있습니다. 빈 <p></p> 조각을 반환합니다.")
            return "<p></p>" # 또는 빈 문자열, 정책에 따라 결정
        
        # EBTG에서 전달된 prompt_template_with_context_and_slot은 이미 {target_language}와
        # {ebtg_lorebook_context} (또는 {{lorebook_context}})가 채워져 있고, {{slot}}만 남아있는 상태입니다.
        # 따라서 여기서는 _construct_prompt를 호출하지 않고, 직접 {{slot}}만 채웁니다.

        use_retry = self.config.get("use_content_safety_retry", True) # Assuming this config exists or add it
        max_attempts = self.config.get("max_content_safety_split_attempts", 3)
        min_size = self.config.get("min_content_safety_chunk_size", 100)

        if use_retry:
            return self._translate_to_xhtml_fragment_recursive(
                text_chunk, target_language, prompt_template_with_context_and_slot,
                current_attempt=0, max_split_attempts=max_attempts, min_chunk_size=min_size
            )
        
        # Original direct call if retry is disabled
        # {{slot}} 플레이스홀더를 현재 청크 텍스트로 대체
        final_prompt_for_api = prompt_template_with_context_and_slot.replace("{{slot}}", text_chunk)
        
        # Gemini API가 반환할 JSON 스키마 정의
        response_schema = {
            "type": "object",
            "properties": {
                "translated_xhtml_fragment": {
                    "type": "string",
                    "description": "A single XHTML fragment, typically a p tag with translated text."
                }
            },
            "required": ["translated_xhtml_fragment"]
        }

        generation_config_dict = {
            "temperature": self.config.get("temperature", 0.5), # XHTML 생성 시에는 약간 낮은 온도 선호 가능
            "top_p": self.config.get("top_p", 0.95),
            "response_mime_type": "application/json",
            "response_schema": response_schema
        }
        model_name = self.config.get("model_name", "gemini-2.0-flash")

        logger.info(f"Gemini API에 XHTML 조각 생성 요청. 모델: {model_name}")
        logger.debug(f"XHTML 조각 생성용 프롬프트 (일부): {final_prompt_for_api[:200]}...")

        try:
            api_response_dict = self.gemini_client.generate_text(
                prompt=final_prompt_for_api,
                model_name=model_name,
                generation_config_dict=generation_config_dict
            )

            if not isinstance(api_response_dict, dict):
                logger.error(f"Gemini API로부터 예상치 못한 응답 유형 수신 (dict 아님): {type(api_response_dict)}. 응답: {str(api_response_dict)[:200]}")
                raise BtgTranslationException("API로부터 유효한 JSON 객체 응답을 받지 못했습니다.")

            translated_fragment = api_response_dict.get("translated_xhtml_fragment")

            if not isinstance(translated_fragment, str):
                logger.error(f"API 응답 JSON에 'translated_xhtml_fragment' 필드가 없거나 문자열이 아닙니다. 응답: {api_response_dict}")
                raise BtgTranslationException("API 응답에서 'translated_xhtml_fragment'를 찾을 수 없거나 형식이 잘못되었습니다.")
            
            logger.debug(f"성공적으로 번역된 XHTML 조각 수신: {translated_fragment[:100]}...")
            return translated_fragment.strip()

        except GeminiContentSafetyException as e_safety:
            logger.warning(f"XHTML 조각 생성 중 콘텐츠 안전 문제 발생: {e_safety}")
            raise BtgTranslationException(f"XHTML 조각 생성 중 콘텐츠 안전 문제: {e_safety}", original_exception=e_safety) from e_safety
        except (GeminiAllApiKeysExhaustedException, GeminiRateLimitException, GeminiInvalidRequestException, GeminiApiException) as e_api_client:
            logger.error(f"XHTML 조각 생성 중 Gemini API 클라이언트 오류: {e_api_client}")
            raise BtgApiClientException(f"XHTML 조각 생성 중 API 오류: {e_api_client}", original_exception=e_api_client) from e_api_client
        except Exception as e_unexpected:
            logger.error(f"XHTML 조각 생성 중 예상치 못한 오류 발생: {e_unexpected}", exc_info=True)
            raise BtgTranslationException(f"XHTML 조각 생성 중 알 수 없는 오류: {e_unexpected}", original_exception=e_unexpected) from e_unexpected

    def _translate_to_xhtml_fragment_recursive(
        self,
        text_chunk: str,
        target_language: str,
        prompt_template_with_context_and_slot: str,
        current_attempt: int,
        max_split_attempts: int,
        min_chunk_size: int
    ) -> str:
        """
        Recursively attempts to translate a text chunk to an XHTML fragment,
        splitting on content safety exceptions.
        """
        if not text_chunk.strip():
            return "" # Or "<p></p>" if empty fragments should be represented

        # EBTG에서 전달된 prompt_template_with_context_and_slot은 이미 {target_language}와
        # {ebtg_lorebook_context} (또는 {{lorebook_context}})가 채워져 있고, {{slot}}만 남아있는 상태입니다.
        # 따라서 여기서는 _construct_prompt를 호출하지 않고, 직접 {{slot}}만 채웁니다.
        final_prompt_for_api = prompt_template_with_context_and_slot.replace("{{slot}}", text_chunk)
        response_schema = {
            "type": "object",
            "properties": {"translated_xhtml_fragment": {"type": "string", "description": "A single XHTML fragment, typically a p tag with translated text."}},
            "required": ["translated_xhtml_fragment"]
        }
        generation_config_dict = {
            "temperature": self.config.get("temperature", 0.5),
            "top_p": self.config.get("top_p", 0.95),
            "response_mime_type": "application/json",
            "response_schema": response_schema
        }
        model_name = self.config.get("model_name", "gemini-2.0-flash")

        try:
            logger.debug(f"Attempt {current_attempt + 1} for XHTML fragment from chunk: {text_chunk[:50]}...")
            api_response_dict = self.gemini_client.generate_text(
                prompt=final_prompt_for_api, model_name=model_name, generation_config_dict=generation_config_dict
            )
            if not isinstance(api_response_dict, dict):
                raise BtgTranslationException("API로부터 유효한 JSON 객체 응답을 받지 못했습니다.")
            translated_fragment = api_response_dict.get("translated_xhtml_fragment")
            if not isinstance(translated_fragment, str):
                raise BtgTranslationException("API 응답에서 'translated_xhtml_fragment'를 찾을 수 없거나 형식이 잘못되었습니다.")
            return translated_fragment.strip()

        except GeminiContentSafetyException as e_safety:
            logger.warning(f"XHTML fragment generation: Content safety issue on attempt {current_attempt + 1} for chunk: {text_chunk[:50]}... Error: {e_safety}")
            if current_attempt < max_split_attempts and len(text_chunk.strip()) > min_chunk_size:
                logger.info(f"Splitting chunk and retrying (attempt {current_attempt + 1}/{max_split_attempts}).")
                sub_chunks = self.chunk_service.split_chunk_recursively(
                    text_chunk, target_size=len(text_chunk) // 2, min_chunk_size=min_chunk_size, max_split_depth=1
                )
                if len(sub_chunks) <= 1: # If not splittable by primary strategy
                    sub_chunks = self.chunk_service.split_chunk_by_sentences(text_chunk, max_sentences_per_chunk=1)
                    if len(sub_chunks) <= 1: # Still not splittable
                        logger.error(f"Cannot split problematic chunk further for XHTML fragment. Chunk: {text_chunk[:50]}...")
                        return f"<p>[Content Safety Error - Unresolvable for chunk: {text_chunk[:30]}...]</p>"

                translated_sub_fragments = []
                for sub_c in sub_chunks:
                    if not sub_c.strip(): continue
                    translated_sub_fragments.append(
                        self._translate_to_xhtml_fragment_recursive(
                            sub_c, target_language, prompt_template_with_context_and_slot,
                            current_attempt + 1, max_split_attempts, min_chunk_size
                        )
                    )
                return "".join(translated_sub_fragments)
            else:
                logger.error(f"Content safety error for XHTML fragment (max attempts or min size reached): {text_chunk[:50]}...")
                return f"<p>[Content Safety Error - Max attempts/min size for: {text_chunk[:30]}...]</p>"
        except (BtgApiClientException, BtgTranslationException, BtgServiceException) as e_general:
            logger.error(f"Error during recursive XHTML fragment translation for chunk {text_chunk[:50]}...: {e_general}")
            raise # Re-raise to be handled by the initial caller or task wrapper
        except Exception as e_unexpected:
            logger.error(f"Unexpected error during recursive XHTML fragment translation for chunk {text_chunk[:50]}...: {e_unexpected}", exc_info=True)
            raise BtgTranslationException(f"Unexpected error generating XHTML fragment: {e_unexpected}", original_exception=e_unexpected) from e_unexpected

    
    def translate_text_with_content_safety_retry(
        self, 
        text_chunk: str, 
        max_split_attempts: int = 3,
        min_chunk_size: int = 100,
        prompt_template: Optional[str] = None # 프롬프트 템플릿 인자 추가
    ) -> str:
        """
        콘텐츠 안전 오류 발생시 청크를 분할하여 재시도하는 번역 메서드
        
        Args:
            text_chunk: 번역할 텍스트
            max_split_attempts: 최대 분할 시도 횟수
            min_chunk_size: 최소 청크 크기
            prompt_template: 번역에 사용할 프롬프트 템플릿

        Returns:
            번역된 텍스트 (실패한 부분은 오류 메시지로 대체)
        """
        try:
            # 1차 시도: 전체 청크 번역
            return self.translate_text(text_chunk, prompt_template=prompt_template)
            
        except BtgTranslationException as e:
            # 검열 오류가 아닌 경우 그대로 예외 발생
            if "콘텐츠 안전 문제" not in str(e):
                raise e
            
            logger.warning(f"콘텐츠 안전 문제 감지. 청크 분할 재시도 시작: {str(e)}")
            return self._translate_with_recursive_splitting(
                text_chunk, max_split_attempts, min_chunk_size, current_attempt=1, prompt_template=prompt_template
            )

    def _translate_with_recursive_splitting(
        self,
        text_chunk: str,
        max_split_attempts: int,
        min_chunk_size: int,
        current_attempt: int = 1,
        prompt_template: Optional[str] = None # 프롬프트 템플릿 인자 추가
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
                translated_part = self.translate_text(sub_chunk.strip(), prompt_template=prompt_template)
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
    
    # --- New methods for XHTML Generation ---

    def _construct_xhtml_generation_prompt(
        self,
        prompt_instructions: str,
        content_items: List[Dict[str, Any]],
        target_language: str
    ) -> str:
        """
        Constructs the full prompt for the Gemini API to generate an XHTML string.
        """
        # Serialize content_items to a JSON string to be embedded in the prompt
        # This makes it clear to the LLM what the structured input is.
        try:
            content_items_json_string = json.dumps(content_items, indent=2, ensure_ascii=False)
        except TypeError as e:
            logger.error(f"Error serializing content_items to JSON: {e}. Content items: {content_items}")
            # Fallback or raise error
            content_items_json_string = str(content_items) # Simple string representation as fallback

        # Assemble the full prompt
        # The prompt_instructions should already guide the LLM on how to use the content_items.
        # We just need to provide the data clearly.
        full_prompt = f"""{prompt_instructions}

Target language for translation of text elements: {target_language}

The content items to be processed into a single XHTML string are provided below as a JSON array.
Each object in the array has a "type" ('text' or 'image') and "data".
For "text" type, "data" is the string to be translated.
For "image" type, "data" is an object with "src" (to be preserved) and "alt" (to be translated if present).

Content Items:
```json
{content_items_json_string}
```

Please generate the complete XHTML string based on these items and the instructions.
The response should be a single JSON object containing the key "translated_xhtml_content" with the generated XHTML string as its value.
"""
        logger.debug(f"Constructed XHTML generation prompt. Length: {len(full_prompt)}")
        logger.debug(f"Prompt (first 500 chars): {full_prompt[:500]}")
        return full_prompt

    def generate_xhtml_from_content_items(
        self,
        prompt_instructions: str,
        content_items: List[Dict[str, Any]],
        target_language: str,
        response_schema: Dict[str, Any] 
    ) -> str:
        """
        Uses GeminiClient to generate a translated XHTML string from structured content items.

        Args:
            prompt_instructions: Detailed instructions for the LLM on how to generate XHTML.
            content_items: A list of dictionaries, where each represents a text block or an image.
            target_language: The target language for translation.
            response_schema: The schema Gemini API should use for its JSON output (from BtgIntegrationService).

        Returns:
            The generated XHTML string.

        Raises:
            BtgTranslationException: If XHTML generation fails or the response is not as expected.
            BtgApiClientException: If there's an issue with the Gemini API call.
        """
        if not self.gemini_client:
            logger.error("GeminiClient is not initialized. Cannot generate XHTML.")
            raise BtgServiceException("GeminiClient is not initialized.")

        full_prompt = self._construct_xhtml_generation_prompt(
            prompt_instructions, content_items, target_language
        )

        # Configuration for the Gemini API call
        # Temperature/TopP might need specific tuning for XHTML generation
        generation_config_dict = {
            "temperature": self.config.get("temperature", 0.5), # Potentially lower temp for more structured output
            "top_p": self.config.get("top_p", 0.95),
            "response_mime_type": "application/json",
            "response_schema": response_schema
        }
        
        model_name = self.config.get("model_name", "gemini-2.0-flash") # Or a model better suited for generation

        logger.info(f"Requesting XHTML generation from Gemini. Model: {model_name}")
        logger.debug(f"Generation Config for XHTML: {generation_config_dict}")

        try:
            api_response = self.gemini_client.generate_text(
                prompt=full_prompt,
                model_name=model_name,
                generation_config_dict=generation_config_dict
            )

            if api_response is None:
                logger.error("Gemini API returned None for XHTML generation.")
                raise BtgApiClientException("API returned no response for XHTML generation.")

            if isinstance(api_response, dict):
                generated_xhtml = api_response.get("translated_xhtml_content")
                if isinstance(generated_xhtml, str):
                    logger.info(f"Successfully received generated XHTML string. Length: {len(generated_xhtml)}")
                    logger.debug(f"Generated XHTML (first 200 chars): {generated_xhtml[:200]}")
                    return generated_xhtml
                else:
                    logger.error(f"API response was a dictionary, but 'translated_xhtml_content' key was missing or not a string. Response: {api_response}")
                    raise BtgTranslationException("Invalid XHTML generation response format: 'translated_xhtml_content' missing or not a string.")
            else:
                # This case should ideally be handled by GeminiClient raising an error if JSON parsing fails
                # when response_mime_type was "application/json".
                logger.error(f"Expected a dictionary (JSON object) from Gemini API for XHTML generation, but received type {type(api_response)}. Response: {str(api_response)[:500]}")
                raise BtgTranslationException(f"Unexpected response type ({type(api_response)}) from API for XHTML generation.")

        except GeminiContentSafetyException as e_safety:
            logger.warning(f"Content safety issue during XHTML generation: {e_safety}")
            raise BtgTranslationException(f"XHTML generation blocked due to content safety: {e_safety}", original_exception=e_safety) from e_safety
        except GeminiAllApiKeysExhaustedException as e_keys:
            logger.error(f"All API keys exhausted during XHTML generation: {e_keys}")
            raise BtgApiClientException(f"All API keys exhausted during XHTML generation: {e_keys}", original_exception=e_keys) from e_keys
        except GeminiRateLimitException as e_rate:
            logger.error(f"API rate limit exceeded during XHTML generation: {e_rate}")
            raise BtgApiClientException(f"API rate limit exceeded during XHTML generation: {e_rate}", original_exception=e_rate) from e_rate
        except GeminiInvalidRequestException as e_invalid:
            logger.error(f"Invalid API request during XHTML generation: {e_invalid}")
            raise BtgApiClientException(f"Invalid API request for XHTML generation: {e_invalid}", original_exception=e_invalid) from e_invalid
        except GeminiApiException as e_api:
            logger.error(f"General Gemini API error during XHTML generation: {e_api}")
            raise BtgApiClientException(f"API error during XHTML generation: {e_api}", original_exception=e_api) from e_api
        except Exception as e:
            logger.error(f"Unexpected error during XHTML generation: {e}", exc_info=True)
            raise BtgTranslationException(f"Unexpected error during XHTML generation: {e}", original_exception=e) from e


if __name__ == '__main__':
    # MockGeminiClient에서 types를 사용하므로, 이 블록 내에서 임포트합니다.
    from google.genai import types as genai_types # Ensure types is imported for hints
    
    sample_config_base = {
        "model_name": "gemini-1.5-flash", "temperature": 0.7, "top_p": 0.9,
        "prompts": "다음 텍스트를 한국어로 번역해주세요. 로어북 컨텍스트: {{lorebook_context}}\n\n번역할 텍스트:\n{{slot}}",
        "enable_dynamic_lorebook_injection": True, # 테스트를 위해 활성화
        "lorebook_json_path": "test_lorebook.json", # 통합된 로어북 경로
        "max_lorebook_entries_per_chunk_injection": 3,
        "max_lorebook_chars_per_chunk_injection": 200,
    }


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

            if is_json_response_expected and "translated_xhtml_content" not in (generation_config_dict.get("response_schema",{}).get("properties",{})): # Distinguish from XHTML gen
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

    # --- Test for XHTML Generation ---
    print("\n--- 4. XHTML 생성 테스트 ---")
    config_xhtml = sample_config_base.copy()
    gemini_client_for_xhtml = MockGeminiClient(auth_credentials="dummy_api_key_xhtml")
    translation_service_xhtml = TranslationService(gemini_client_for_xhtml, config_xhtml)

    test_prompt_instructions = "You are an expert XHTML generator. Translate text to Korean."
    test_content_items = [
        {"type": "text", "data": "This is the first paragraph."},
        {"type": "image", "data": {"src": "images/image1.png", "alt": "A cute cat"}},
        {"type": "text", "data": "This is the second paragraph following the image."}
    ]
    test_target_language = "ko"
    test_response_schema = {
        "type": "OBJECT",
        "properties": {"translated_xhtml_content": {"type": "STRING"}}
    }

    try:
        generated_xhtml_string = translation_service_xhtml.generate_xhtml_from_content_items(
            prompt_instructions=test_prompt_instructions,
            content_items=test_content_items,
            target_language=test_target_language,
            response_schema=test_response_schema
        )
        print(f"생성된 XHTML: {generated_xhtml_string}")
        assert "<html>" in generated_xhtml_string
        assert "[번역됨] This is the first paragraph." in generated_xhtml_string # Check if text was processed
        assert "src='images/image1.png'" in generated_xhtml_string
    except Exception as e:
        print(f"XHTML 생성 테스트 오류: {e}")

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
