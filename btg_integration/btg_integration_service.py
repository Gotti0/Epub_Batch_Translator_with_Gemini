import sys
from pathlib import Path

# For direct execution or when the package context isn't correctly set,
# ensure the project root (EBTG_Project) is in sys.path.
# This allows `from btg_module...` imports to work.
if __name__ == '__main__' or __package__ is None:
    _project_root = Path(__file__).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

from typing import List, Dict, Any, Optional
import logging # 로깅 추가

# 가상으로 BTG 모듈의 AppService를 임포트합니다.
# 실제 BTG 모듈 구조에 따라 경로를 수정해야 합니다.
from btg_module.app_service import AppService as BtgAppService
# from ebtg.ebtg_dtos import (
# BtgPlainTextTranslationRequestDto, BtgPlainTextTranslationResponseDto,
# BtgStructuredReconstructionRequestDto, BtgStructuredReconstructionResponseDto,
# BtgDirectStructuredTranslationRequestDto, BtgDirectStructuredTranslationResponseDto
# )
# 참고: 위 DTO들은 ebtg/ebtg_dtos.py 파일에 정의되어야 합니다.

# BTG 모듈 예외 임포트
from btg_module.exceptions import (
    BtgConfigException, BtgServiceException, BtgApiClientException,
    BtgApiRateLimitException, BtgApiContentSafetyException, BtgApiInvalidRequestException,
    BtgTranslationException
)
from btg_module.gemini_client import GeminiAllApiKeysExhaustedException

# EBTG 예외 임포트 (위에서 생성한 파일 기준)
from ..ebtg.ebtg_exceptions import (
    EbtgIntegrationError, EbtgConfigError, EbtgAuthenticationError,
    EbtgRateLimitError, EbtgContentSafetyError, EbtgTranslationError,
    EbtgResourceNotFoundError, EbtgServiceUnavailableError, EbtgApiCommsError
)

logger = logging.getLogger(__name__)

class BtgIntegrationService:
    """
    EBTG와 BTG 모듈 간의 인터페이스 역할을 하는 서비스입니다.
    Phase별로 다른 번역 요청 유형을 처리합니다.
    """

    def __init__(self, 
                 btg_app_service_instance: Optional[BtgAppService] = None, 
                 integration_config: Optional[Dict[str, Any]] = None,
                 btg_module_config_file_path: Optional[str] = None):
        """
        BtgIntegrationService를 초기화합니다.

        Args:
            btg_app_service_instance: BTG 모듈의 AppService 인스턴스 (선택 사항, 주입용).
            integration_config: EBTG가 BTG 모듈 연동 시 사용할 설정 (선택 사항).
                                이 설정은 BtgAppService 내부 설정을 직접 변경하지 않으며,
                                BtgIntegrationService가 BTG 메소드 호출 시 파라미터로 사용하거나
                                BTG 설정 파일 관리를 EBTG 레벨에서 수행해야 함을 의미할 수 있습니다.
            btg_module_config_file_path: BtgAppService가 로드할 설정 파일 경로 (선택 사항).
                                         None이면 BtgAppService는 기본 경로의 config.json을 사용합니다.
        """
        if btg_app_service_instance:
            self.btg_app_service = btg_app_service_instance
            logger.info("Provided BtgAppService instance will be used.")
        else:
            try:
                logger.info(f"Creating a new BtgAppService instance. Config file path: {btg_module_config_file_path or 'default'}")
                self.btg_app_service = BtgAppService(config_file_path=btg_module_config_file_path)
            except BtgConfigException as e:
                logger.error(f"Failed to initialize BtgAppService due to config error: {e}", exc_info=True)
                raise EbtgConfigError(f"BTG module configuration error: {e.message}", original_exception=e) from e
            except Exception as e: # Catch any other unexpected init errors
                logger.error(f"Unexpected error initializing BtgAppService: {e}", exc_info=True)
                raise EbtgIntegrationError(f"Failed to initialize BTG AppService: {e}", original_exception=e) from e

        self.integration_config = integration_config if integration_config else {}
        logger.info("BtgIntegrationService initialized.")
        
        if not self.btg_app_service.translation_service:
            logger.warning("BtgAppService's TranslationService is not initialized. Plain text translation might fail.")
        if not self.btg_app_service.gemini_client:
            logger.warning("BtgAppService's GeminiClient is not initialized. API calls will fail.")

    def translate_plain_texts_for_phase1_2(
        self,
        texts_with_ids: List[Dict[str, str]], # 예: [{"id": "p1", "text": "Hello"}, {"id": "h1_1", "text": "World"}]
        source_lang: str,
        target_lang: str
    ) -> List[Dict[str, str]]: # 예: [{"id": "p1", "translated_text": "안녕하세요"}, {"id": "h1_1", "translated_text": "세계"}]
        """
        Phase 1 및 2: 순수 텍스트 목록을 번역합니다.
        각 텍스트는 원본 구조 식별자(ID)와 함께 제공됩니다.

        Args:
            texts_with_ids: 번역할 텍스트와 해당 ID를 포함하는 딕셔너리 리스트.
            source_lang: 원본 언어 코드 (예: "en").
            target_lang: 대상 언어 코드 (예: "ko").

        Returns:
            번역된 텍스트와 원본 ID를 포함하는 딕셔너리 리스트.
            실제로는 BtgPlainTextTranslationResponseDto 같은 DTO를 사용할 수 있습니다.
        """
        if not self.btg_app_service.translation_service:
            logger.error("BTG TranslationService is not available for Phase 1/2.")
            raise EbtgServiceUnavailableError("BTG TranslationService is not initialized or available.")

        logger.info(f"Phase 1/2: Translating {len(texts_with_ids)} plain texts from {source_lang} to {target_lang}")
        
        translated_results = []
        for item in texts_with_ids:
            item_id = item["id"]
            text_to_translate = item["text"]
            try:
                # BTG의 TranslationService.translate_text는 source/target lang을 직접 받지 않습니다.
                # 프롬프트나 BtgAppService.config를 통해 번역 방향이 설정되어야 합니다.
                # EBTG는 필요시 BtgAppService.config를 업데이트하거나, TranslationService에
                # 언어 설정을 전달할 수 있는 메소드를 추가해야 할 수 있습니다.
                translated_text = self.btg_app_service.translation_service.translate_text(text_to_translate)
                translated_results.append({"id": item_id, "translated_text": translated_text})
            except GeminiAllApiKeysExhaustedException as e:
                logger.error(f"Authentication error (all API keys exhausted) for id {item_id}: {e}", exc_info=True)
                raise EbtgAuthenticationError(f"BTG API authentication failed for id {item_id}: All keys exhausted.", original_exception=e) from e
            except BtgApiInvalidRequestException as e: # Catches auth errors, model not found etc.
                logger.error(f"Invalid API request (auth/model) for id {item_id}: {e}", exc_info=True)
                if "key" in e.message.lower() or "auth" in e.message.lower():
                    raise EbtgAuthenticationError(f"BTG API authentication failed for id {item_id}: {e.message}", original_exception=e) from e
                elif "model" in e.message.lower() or "not found" in e.message.lower():
                    raise EbtgResourceNotFoundError(f"BTG API resource not found for id {item_id}: {e.message}", original_exception=e) from e
                raise EbtgApiCommsError(f"Invalid BTG API request for id {item_id}: {e.message}", original_exception=e) from e
            except BtgApiRateLimitException as e:
                logger.warning(f"Rate limit hit for id {item_id}: {e}", exc_info=True)
                raise EbtgRateLimitError(f"BTG API rate limit exceeded for id {item_id}.", original_exception=e) from e
            except BtgApiContentSafetyException as e:
                logger.warning(f"Content safety issue for id {item_id}: {e}", exc_info=True)
                raise EbtgContentSafetyError(f"BTG API content safety block for id {item_id}.", original_exception=e) from e
            except BtgApiClientException as e: # General API client errors
                logger.error(f"BTG API client error for id {item_id}: {e}", exc_info=True)
                raise EbtgApiCommsError(f"BTG API communication error for id {item_id}: {e.message}", original_exception=e) from e
            except BtgTranslationException as e:
                logger.error(f"BTG translation error for id {item_id}: {e}", exc_info=True)
                raise EbtgTranslationError(f"BTG translation failed for id {item_id}: {e.message}", original_exception=e) from e
            except Exception as e: # Catch-all for other unexpected BTG errors
                logger.error(f"Unexpected error translating text for id {item_id}: {e}", exc_info=True)
                raise EbtgIntegrationError(f"Unexpected error during BTG translation for id {item_id}: {e}", original_exception=e) from e
        return translated_results

    def reconstruct_content_for_phase3_pipeline(
        self,
        primary_translated_text: str, # 1차 번역된 전체 텍스트 또는 주요 부분
        original_html_structure_info: Any, # 원본 HTML 구조 정보 (예: 단순화된 DOM 트리, XPath 목록 등)
        response_schema_name: str # 사용할 Gemini 응답 스키마 이름 (config/response_schemas/ 에서 참조)
    ) -> Dict[str, Any]:
        """
        Phase 3 (2단계 파이프라인): 1차 번역된 텍스트와 원본 HTML 구조 정보를 바탕으로
        Gemini API에 구조화된 재구성을 요청합니다.

        Args:
            primary_translated_text: 1차 번역된 텍스트.
            original_html_structure_info: 원본 HTML 구조를 나타내는 데이터.
            response_schema_name: Gemini가 반환해야 할 JSON 구조를 정의하는 스키마의 이름.

        Returns:
            Gemini로부터 받은 구조화된 JSON 응답.
            실제로는 BtgStructuredReconstructionResponseDto 같은 DTO를 사용할 수 있습니다.
        """
        # TODO: BTG 모듈의 btg_module.translation_service.TranslationService에
        #       request_structured_reconstruction(...)
        #       와 같은 메소드를 구현해야 합니다.
        #       이 메소드는 Gemini API의 JSON 모드를 사용하여 구조화된 출력을 요청합니다.
        #       self.integration_config (또는 그 일부)를 generation_config_overrides로 전달할 수 있습니다.
        if not self.btg_app_service.translation_service:
            logger.error("BTG TranslationService is not available for Phase 3 pipeline.")
            raise EbtgServiceUnavailableError("BTG TranslationService is not initialized or available for Phase 3 pipeline.")

        if not hasattr(self.btg_app_service.translation_service, 'request_structured_reconstruction'):
            logger.error("BTG TranslationService does not have 'request_structured_reconstruction' method.")
            raise EbtgIntegrationError("Required method 'request_structured_reconstruction' not found in BTG TranslationService.")

        logger.info(f"Phase 3 (Pipeline): Reconstructing content with schema '{response_schema_name}'")
        try:
            return self.btg_app_service.translation_service.request_structured_reconstruction(
                primary_translated_text, original_html_structure_info, response_schema_name, self.integration_config
            )
        except GeminiAllApiKeysExhaustedException as e:
            logger.error(f"Authentication error (all API keys exhausted) during Phase 3 pipeline: {e}", exc_info=True)
            raise EbtgAuthenticationError("BTG API authentication failed (all keys exhausted) for Phase 3 pipeline.", original_exception=e) from e
        except BtgApiInvalidRequestException as e:
            logger.error(f"Invalid API request (auth/model) for Phase 3 pipeline: {e}", exc_info=True)
            if "key" in e.message.lower() or "auth" in e.message.lower():
                raise EbtgAuthenticationError(f"BTG API authentication failed for Phase 3 pipeline: {e.message}", original_exception=e) from e
            raise EbtgApiCommsError(f"Invalid BTG API request for Phase 3 pipeline: {e.message}", original_exception=e) from e
        except BtgApiRateLimitException as e:
            logger.warning(f"Rate limit hit for Phase 3 pipeline: {e}", exc_info=True)
            raise EbtgRateLimitError("BTG API rate limit exceeded for Phase 3 pipeline.", original_exception=e) from e
        except BtgApiContentSafetyException as e:
            logger.warning(f"Content safety issue for Phase 3 pipeline: {e}", exc_info=True)
            raise EbtgContentSafetyError("BTG API content safety block for Phase 3 pipeline.", original_exception=e) from e
        except BtgApiClientException as e:
            logger.error(f"BTG API client error for Phase 3 pipeline: {e}", exc_info=True)
            raise EbtgApiCommsError(f"BTG API communication error for Phase 3 pipeline: {e.message}", original_exception=e) from e
        except Exception as e: # Catch-all for other unexpected BTG errors
            logger.error(f"Unexpected error during Phase 3 pipeline reconstruction: {e}", exc_info=True)
            raise EbtgIntegrationError(f"Unexpected error during BTG Phase 3 pipeline reconstruction: {e}", original_exception=e) from e

    def translate_specific_content_with_structure_for_phase3(
        self,
        content_to_translate: str, # 번역할 특정 콘텐츠 (예: 표의 HTML 문자열)
        source_lang: str,
        target_lang: str,
        response_schema_name: str # 사용할 Gemini 응답 스키마 이름
    ) -> Dict[str, Any]:
        """
        Phase 3 (제한적 구조화 출력): 특정 콘텐츠(예: 표)에 대해 직접 구조화된 출력을 요청합니다.

        Args:
            content_to_translate: 번역 및 구조화할 원본 콘텐츠.
            source_lang: 원본 언어 코드.
            target_lang: 대상 언어 코드.
            response_schema_name: Gemini가 반환해야 할 JSON 구조를 정의하는 스키마의 이름.

        Returns:
            Gemini로부터 받은 구조화된 JSON 응답.
            실제로는 BtgDirectStructuredTranslationResponseDto 같은 DTO를 사용할 수 있습니다.
        """
        # TODO: BTG 모듈의 btg_module.translation_service.TranslationService에
        #       request_direct_structured_translation(...)
        #       와 같은 메소드를 구현해야 합니다.
        #       이 메소드는 Gemini API의 JSON 모드를 사용합니다.
        #       source_lang, target_lang을 사용하여 적절한 프롬프트를 구성해야 합니다.
        if not self.btg_app_service.translation_service:
            logger.error("BTG TranslationService is not available for Phase 3 direct structured translation.")
            raise EbtgServiceUnavailableError("BTG TranslationService is not initialized or available for Phase 3 direct.")

        if not hasattr(self.btg_app_service.translation_service, 'request_direct_structured_translation'):
            logger.error("BTG TranslationService does not have 'request_direct_structured_translation' method.")
            raise EbtgIntegrationError("Required method 'request_direct_structured_translation' not found in BTG TranslationService.")
            
        logger.info(f"Phase 3 (Direct): Translating specific content with structure schema '{response_schema_name}' from {source_lang} to {target_lang}")
        try:
            return self.btg_app_service.translation_service.request_direct_structured_translation(
                content_to_translate, source_lang, target_lang, response_schema_name, self.integration_config
            )
        except GeminiAllApiKeysExhaustedException as e:
            logger.error(f"Authentication error (all API keys exhausted) during Phase 3 direct: {e}", exc_info=True)
            raise EbtgAuthenticationError("BTG API authentication failed (all keys exhausted) for Phase 3 direct.", original_exception=e) from e
        except BtgApiInvalidRequestException as e:
            logger.error(f"Invalid API request (auth/model) for Phase 3 direct: {e}", exc_info=True)
            if "key" in e.message.lower() or "auth" in e.message.lower():
                raise EbtgAuthenticationError(f"BTG API authentication failed for Phase 3 direct: {e.message}", original_exception=e) from e
            raise EbtgApiCommsError(f"Invalid BTG API request for Phase 3 direct: {e.message}", original_exception=e) from e
        except BtgApiRateLimitException as e:
            logger.warning(f"Rate limit hit for Phase 3 direct: {e}", exc_info=True)
            raise EbtgRateLimitError("BTG API rate limit exceeded for Phase 3 direct.", original_exception=e) from e
        except BtgApiContentSafetyException as e:
            logger.warning(f"Content safety issue for Phase 3 direct: {e}", exc_info=True)
            raise EbtgContentSafetyError("BTG API content safety block for Phase 3 direct.", original_exception=e) from e
        except BtgApiClientException as e:
            logger.error(f"BTG API client error for Phase 3 direct: {e}", exc_info=True)
            raise EbtgApiCommsError(f"BTG API communication error for Phase 3 direct: {e.message}", original_exception=e) from e
        except Exception as e: # Catch-all for other unexpected BTG errors
            logger.error(f"Unexpected error during Phase 3 direct structured translation: {e}", exc_info=True)
            raise EbtgIntegrationError(f"Unexpected error during BTG Phase 3 direct translation: {e}", original_exception=e) from e

if __name__ == '__main__':
    # 테스트를 위한 기본 로깅 설정
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # 간단한 테스트용 코드
    # BtgAppService가 기본 config.json을 로드하도록 btg_module_config_file_path를 None으로 둡니다.
    # integration_config는 BtgIntegrationService가 사용할 수 있는 추가 설정입니다.
    try:
        integration_service = BtgIntegrationService(integration_config={"mode": "test"})

        # Phase 1/2 테스트
        plain_texts = [
            {"id": "p1", "text": "This is a paragraph."},
            {"id": "h1_1", "text": "This is a heading."}
        ]
        # 실제 번역을 위해서는 BTG 모듈의 config.json에 유효한 API 키 등이 설정되어 있어야 합니다.
        # 또는 BtgAppService를 Mocking해야 합니다.
        # 여기서는 예외 처리를 보여주기 위해 호출을 시도합니다.
        try:
            translated_plain_texts = integration_service.translate_plain_texts_for_phase1_2(plain_texts, "en", "ko")
            logger.info(f"Phase 1/2 Result: {translated_plain_texts}")
        except EbtgBaseException as e:
            logger.error(f"Phase 1/2 test caught EBTG exception: {e}")

        # Phase 3 (2단계 파이프라인) 테스트
        try:
            reconstructed_content = integration_service.reconstruct_content_for_phase3_pipeline(
                "이것은 1차 번역된 텍스트입니다.",
                {"type": "simplified_dom", "elements": ["p", "h1"]},
                "phase3_basic_structure.json"
            )
            logger.info(f"Phase 3 Pipeline Result (Placeholder): {reconstructed_content}")
        except EbtgBaseException as e:
            logger.error(f"Phase 3 Pipeline test caught EBTG exception: {e}")

        # Phase 3 (제한적 구조화 출력) 테스트
        try:
            structured_translation = integration_service.translate_specific_content_with_structure_for_phase3(
                "<table><tr><td>Original Cell</td></tr></table>",
                "en", "ko",
                "phase3_table_structure.json"
            )
            logger.info(f"Phase 3 Direct Result (Placeholder): {structured_translation}")
        except EbtgBaseException as e:
            logger.error(f"Phase 3 Direct test caught EBTG exception: {e}")

    except EbtgBaseException as e:
        logger.critical(f"Failed to initialize BtgIntegrationService: {e}")