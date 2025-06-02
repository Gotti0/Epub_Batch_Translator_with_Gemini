from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class BtgPlainTextTranslationRequestDto:
    """
    Phase 1/2: 순수 텍스트 목록 번역 요청 DTO.
    BTG 모듈의 일반 텍스트 번역 기능을 호출할 때 사용됩니다.
    """
    texts_with_ids: List[Dict[str, str]] # 예: [{"id": "p1", "text": "Hello"}, {"id": "h1_1", "text": "World"}]
    source_lang: str
    target_lang: str
    # BTG 모듈의 설정을 EBTG에서 동적으로 오버라이드하고 싶을 경우 사용
    # 예: 특정 프롬프트 템플릿 사용, 특정 로어북 임시 적용 등
    # btg_config_overrides: Optional[Dict[str, Any]] = None 

@dataclass
class BtgPlainTextTranslationResponseDto:
    """
    Phase 1/2: 순수 텍스트 목록 번역 응답 DTO.
    """
    # [{"id": "p1", "translated_text": "안녕하세요"}, {"id": "h1_1", "translated_text": "세계"}]
    # 또는 [{"id": "p1", "error": "API_KEY_INVALID"}] 형태도 포함 가능
    translated_items: List[Dict[str, Any]] 
    success_overall: bool = True # 전체 요청에 대한 성공 여부 (개별 항목 실패 가능)
    error_message_overall: Optional[str] = None # 전체 요청에 대한 오류 메시지

@dataclass
class BtgStructuredReconstructionRequestDto:
    """
    Phase 3 (2단계 파이프라인): 1차 번역된 텍스트와 원본 HTML 구조 정보를 바탕으로
    Gemini API에 구조화된 재구성을 요청하는 DTO.
    """
    primary_translated_text: str
    original_html_structure_info: Any # 예: {"type": "simplified_dom", "elements": ["p", "h1"]}
    response_schema_name: str # 예: "phase3_basic_structure.json"
    # BTG 모듈의 GeminiClient.generate_text 호출 시 generation_config_dict를 오버라이드
    generation_config_overrides: Optional[Dict[str, Any]] = None

@dataclass
class BtgDirectStructuredTranslationRequestDto:
    """
    Phase 3 (제한적 구조화 출력): 특정 콘텐츠에 대해 직접 구조화된 번역 출력을 요청하는 DTO.
    """
    content_to_translate: str # 예: "<table>...</table>"
    source_lang: str
    target_lang: str
    response_schema_name: str # 예: "phase3_table_structure.json"
    # BTG 모듈의 GeminiClient.generate_text 호출 시 generation_config_dict를 오버라이드
    generation_config_overrides: Optional[Dict[str, Any]] = None

@dataclass
class BtgStructuredResponseDto:
    """
    Phase 3: 구조화된 출력 요청에 대한 공통 응답 DTO.
    """
    structured_data: Optional[Dict[str, Any]] # Gemini로부터 받은 파싱된 JSON 응답
    success: bool
    error_message: Optional[str] = None
    raw_response_preview: Optional[str] = None # 디버깅용 원본 API 응답 (일부)


if __name__ == '__main__':
    # DTO 사용 예시
    print("--- EBTG DTO 사용 예시 ---")

    # Phase 1/2 요청
    plain_text_req = BtgPlainTextTranslationRequestDto(
        texts_with_ids=[{"id": "p1", "text": "Hello world."}, {"id": "s1", "text": "This is a span."}],
        source_lang="en",
        target_lang="ko"
    )
    print(f"Phase 1/2 요청 DTO: {plain_text_req}")

    # Phase 1/2 응답
    plain_text_res = BtgPlainTextTranslationResponseDto(
        translated_items=[
            {"id": "p1", "translated_text": "안녕 세상아."},
            {"id": "s1", "translated_text": "이것은 스팬입니다."}
        ]
    )
    print(f"Phase 1/2 응답 DTO: {plain_text_res}")

    # Phase 3 (2단계 파이프라인) 요청
    structured_recon_req = BtgStructuredReconstructionRequestDto(
        primary_translated_text="이것은 1차 번역된 텍스트입니다.",
        original_html_structure_info={"type": "simplified_dom", "elements": ["p", "h1"]},
        response_schema_name="chapter_content.json",
        generation_config_overrides={"temperature": 0.5}
    )
    print(f"Phase 3 (Pipeline) 요청 DTO: {structured_recon_req}")

    # Phase 3 (직접 구조화) 요청
    direct_structured_req = BtgDirectStructuredTranslationRequestDto(
        content_to_translate="<table><tr><td>Name</td><td>Age</td></tr><tr><td>Alice</td><td>30</td></tr></table>",
        source_lang="en",
        target_lang="ko",
        response_schema_name="table_translation.json"
    )
    print(f"Phase 3 (Direct) 요청 DTO: {direct_structured_req}")

    # Phase 3 응답
    structured_res = BtgStructuredResponseDto(
        structured_data={"title": "번역된 제목", "paragraphs": ["첫 번째 문단.", "두 번째 문단."]},
        success=True
    )
    print(f"Phase 3 응답 DTO: {structured_res}")