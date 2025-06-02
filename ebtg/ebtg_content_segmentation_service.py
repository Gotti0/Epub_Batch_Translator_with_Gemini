# c:\Users\Hyunwoo_Room\Downloads\EBTG_Project\ebtg\ebtg_content_segmentation_service.py
from typing import List, Dict, Any, Optional

# from .ebtg_logger import EbtgLogger # 이전 import 문
from btg_module.logger_config import setup_logger # 수정된 import 문

# 이 서비스 자체의 로거를 설정합니다.
logger = setup_logger(__name__)

class ContentSegmentationService:
    """
    Responsible for segmenting content items extracted from an XHTML file.
    In the v7 architecture, where the API generates the entire XHTML,
    segmentation is primarily needed if a single XHTML file's content
    (text + image alt-texts + prompt instructions) exceeds API token limits.

    This is different from BTG's internal chunking for translating large text blocks.
    This service operates on the list of {"type": "text", ...} and {"type": "image", ...} items
    before they are sent to BtgIntegrationService.
    """

    def __init__(self): # logger 인자 제거
        self.logger = logger # 클래스 레벨에서 설정된 로거 사용 (또는 self.logger = setup_logger(__name__) 로 직접 설정)

    def segment_content_items(
        self,
        content_items: List[Dict[str, Any]],
        file_name: str, # For logging purposes
        # max_tokens_per_segment: Optional[int] = None # Placeholder for future token-based splitting
    ) -> List[List[Dict[str, Any]]]:
        """
        Segments a list of content items into one or more "document fragments".

        Args:
            content_items: The list of text and image items from SimplifiedHtmlExtractor.
            file_name: The name of the XHTML file these items belong to.
            # max_tokens_per_segment: (Future) Estimated max tokens for items in a segment.

        Returns:
            A list of segments. Each segment is a list of content_items.
            For the initial implementation, this will always return a list containing
            the original content_items list as its single element.
        """
        self.logger.log_debug(f"ContentSegmentationService: Processing content items for '{file_name}'.")

        # Phase 1: No actual segmentation. Treat the whole file's content as one segment.
        # Future enhancements could implement logic here to split `content_items`
        # into multiple sub-lists if `max_tokens_per_segment` is provided and
        # an estimation indicates the current list is too large.
        #
        # For example (pseudo-code for future):
        # if max_tokens_per_segment:
        #     segments = []
        #     current_segment = []
        #     current_tokens = 0
        #     for item in content_items:
        #         item_tokens = self._estimate_item_tokens(item) # Needs a helper method
        #         if current_tokens + item_tokens > max_tokens_per_segment and current_segment:
        #             segments.append(current_segment)
        #             current_segment = []
        #             current_tokens = 0
        #         current_segment.append(item)
        #         current_tokens += item_tokens
        #     if current_segment:
        #         segments.append(current_segment)
        #     self.logger.log_info(f"Segmented content for '{file_name}' into {len(segments)} fragments based on token limits.")
        #     return segments

        self.logger.log_info(f"ContentSegmentationService: '{file_name}' content treated as a single segment (Phase 1 behavior).")
        return [content_items]

    # def _estimate_item_tokens(self, item: Dict[str, Any]) -> int:
    #     # Placeholder for a method to estimate token count for a content item
    #     # This would be model-specific or a general heuristic.
    #     return 0