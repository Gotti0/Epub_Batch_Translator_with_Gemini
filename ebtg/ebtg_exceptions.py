# ebtg_exceptions.py
from typing import Optional, Any
import traceback # For storing traceback string

class EbtgBaseException(Exception):
    """EBTG 모듈의 모든 사용자 정의 예외에 대한 기본 클래스입니다."""
    def __init__(
        self,
        message: str,
        original_exception: Optional[BaseException] = None,
        details: Optional[Any] = None,
        include_traceback: bool = False
    ):
        super().__init__(message)
        self.message = message
        self.original_exception = original_exception
        self.details = details
        self.traceback_str = None
        if include_traceback and original_exception:
            # Capture traceback at the point of this exception's creation if an original exists
            try:
                # If original_exception has a traceback, use it. Otherwise, capture current.
                if hasattr(original_exception, '__traceback__') and original_exception.__traceback__:
                    self.traceback_str = "".join(traceback.format_exception(type(original_exception), original_exception, original_exception.__traceback__))
                else:
                    self.traceback_str = traceback.format_exc()
            except Exception: # Fallback if formatting fails for some reason
                 self.traceback_str = "Traceback could not be formatted."

    def __str__(self) -> str:
        base_str = f"{self.__class__.__name__}: {self.message}"
        if self.original_exception:
            base_str += f" (Original exception: {type(self.original_exception).__name__}: {str(self.original_exception)})"
        if self.details:
            base_str += f" (Details: {self.details})"
        if self.traceback_str:
            base_str += f"\n--- Original Traceback (Captured) ---\n{self.traceback_str}\n--- End Traceback ---"
        return base_str

# --- Integration Errors (with BTG module) ---
class EbtgIntegrationError(EbtgBaseException):
    """EBTG와 BTG 모듈 간의 연동 중 발생하는 일반적인 오류입니다."""
    pass

class EbtgConfigError(EbtgIntegrationError):
    """BTG 모듈 설정 또는 EBTG-BTG 연동 설정 관련 오류입니다."""
    pass

class EbtgAuthenticationError(EbtgIntegrationError):
    """BTG 모듈 API 인증 관련 오류입니다 (예: API 키 문제)."""
    pass

class EbtgRateLimitError(EbtgIntegrationError):
    """BTG 모듈 API 사용량 제한 초과 오류입니다."""
    pass

class EbtgContentSafetyError(EbtgIntegrationError):
    """BTG 모듈 API 콘텐츠 안전 관련 오류입니다."""
    pass

class EbtgTranslationError(EbtgIntegrationError):
    """BTG 모듈에서의 번역 처리 중 특정 오류입니다."""
    pass

class EbtgResourceNotFoundError(EbtgIntegrationError):
    """BTG 모듈 API가 요청한 리소스(예: 모델)를 찾을 수 없을 때 발생합니다."""
    pass

class EbtgServiceUnavailableError(EbtgIntegrationError):
    """BTG 모듈의 특정 서비스(예: TranslationService)가 사용 불가능할 때 발생합니다."""
    pass

class EbtgApiCommsError(EbtgIntegrationError):
    """BTG 모듈과의 API 통신 중 일반적인 오류 (예: 네트워크 문제, 잘못된 응답 형식 등)."""
    pass

class ApiXhtmlGenerationError(EbtgIntegrationError):
    """BTG 모듈 또는 Gemini API를 통해 XHTML 문자열을 생성하는 과정에서 발생하는 오류입니다 (아키텍처 v7)."""
    pass


# --- EBTG Internal Processing Errors ---
class EbtgProcessingError(EbtgBaseException):
    """EBTG 내부 데이터 처리 중 발생하는 일반적인 오류입니다."""
    pass

class EbtgFileProcessingError(EbtgProcessingError):
    """EBTG 내부 파일 처리 (EPUB, HTML 등) 중 발생하는 오류입니다."""
    pass

class DomManipulationError(EbtgFileProcessingError):
    """
    HTML DOM 구조를 분석하거나 조작하는 과정에서 발생하는 오류입니다.
    예: 특정 요소를 찾지 못하거나, 예상치 못한 DOM 구조를 만났을 때.
    """
    pass

class HtmlReconstructionError(EbtgFileProcessingError):
    """
    번역된 텍스트와 원본 HTML 구조를 바탕으로 최종 HTML을 재구성하는 과정에서
    발생하는 오류입니다.
    예: 구조 불일치, 누락된 요소, 잘못된 삽입 위치 등.
    """
    pass

class XhtmlExtractionError(EbtgFileProcessingError):
    """
    XHTML 파일에서 텍스트 블록 및 이미지 정보를 추출하는 과정(예: SimplifiedHtmlExtractor)에서
    발생하는 오류입니다 (아키텍처 v7).
    """
    pass

# 추가적인 EBTG 특정 예외들을 여기에 정의할 수 있습니다.