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
        max_items_per_segment: int 
    ) -> List[List[Dict[str, Any]]]:
        """
        Segments a list of content items into one or more "document fragments".

        Args:
            content_items: The list of text and image items from SimplifiedHtmlExtractor.
            file_name: The name of the XHTML file these items belong to.
            max_items_per_segment: The maximum number of content items allowed in a single segment.
                                   If 0 or negative, no segmentation by item count occurs.

        Returns:
            A list of segments. Each segment is a list of content_items.
        """
        self.logger.debug(f"ContentSegmentationService: Processing content items for '{file_name}'. Original item count: {len(content_items)}, Max items per segment: {max_items_per_segment}")

        if not content_items:
            self.logger.info(f"ContentSegmentationService: No content items to segment for '{file_name}'.")
            return []

        if max_items_per_segment <= 0 or len(content_items) <= max_items_per_segment:
            self.logger.info(f"ContentSegmentationService: '{file_name}' content ({len(content_items)} items) treated as a single segment (max_items_per_segment: {max_items_per_segment}).")
            return [content_items]

        segments: List[List[Dict[str, Any]]] = []
        for i in range(0, len(content_items), max_items_per_segment):
            segment = content_items[i:i + max_items_per_segment]
            segments.append(segment)
        
        self.logger.info(f"ContentSegmentationService: Segmented content for '{file_name}' into {len(segments)} fragments, each with up to {max_items_per_segment} items.")
        return segments