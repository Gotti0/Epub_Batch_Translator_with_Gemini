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
        target_char_length_per_segment: int  # Changed from max_items_per_segment
    ) -> List[List[Dict[str, Any]]]:
        """
        Segments a list of content items into one or more "document fragments"
        based on a target character length for the content within each segment.

        Args:
            content_items: The list of text and image items from SimplifiedHtmlExtractor.
            file_name: The name of the XHTML file these items belong to.
            target_char_length_per_segment: The target character length for the sum of
                                            text data and alt text within a segment.
                                            If 0 or negative, no character-based segmentation occurs.

        Returns:
            A list of segments. Each segment is a list of content_items.
        """
        self.logger.debug(f"ContentSegmentationService: Processing content items for '{file_name}'. Original item count: {len(content_items)}, Target chars per segment: {target_char_length_per_segment}")

        if not content_items:
            self.logger.info(f"ContentSegmentationService: No content items to segment for '{file_name}'.")
            return []

        if target_char_length_per_segment <= 0:
            self.logger.info(f"ContentSegmentationService: Target character length is {target_char_length_per_segment}. '{file_name}' content ({len(content_items)} items) treated as a single segment.")
            return [content_items]

        segments: List[List[Dict[str, Any]]] = []
        current_segment_items: List[Dict[str, Any]] = []
        current_segment_char_count = 0

        # Rough estimate of overhead per item for its structural representation in a prompt
        # This is a heuristic and might need adjustment.
        ITEM_STRUCTURE_OVERHEAD_ESTIMATE_TEXT = 20  # e.g., for '{"type":"text","data":""}' or "- Text: "
        ITEM_STRUCTURE_OVERHEAD_ESTIMATE_IMAGE = 30 # e.g., for '{"type":"image","data":{"src":"","alt":""}}' or "- Image: src='...', alt='...'"

        for item in content_items:
            item_content_char_estimate = 0
            item_overhead_estimate = 0

            if item.get("type") == "text":
                item_content_char_estimate = len(item.get("data", ""))
                item_overhead_estimate = ITEM_STRUCTURE_OVERHEAD_ESTIMATE_TEXT
            elif item.get("type") == "image":
                # For images, primarily count alt text as it's the translatable part.
                # Src might be long but isn't directly part of the "text volume" for translation.
                item_content_char_estimate = len(item.get("data", {}).get("alt", ""))
                item_overhead_estimate = ITEM_STRUCTURE_OVERHEAD_ESTIMATE_IMAGE

            item_total_char_contribution = item_content_char_estimate + item_overhead_estimate

            # If adding the current item would exceed the target length,
            # finalize the current segment and start a new one.
            # Exception: if the current segment is empty, add the item anyway (even if it's large).
            if current_segment_items and \
               (current_segment_char_count + item_total_char_contribution > target_char_length_per_segment):
                segments.append(current_segment_items)
                self.logger.debug(f"Segment created for '{file_name}' with ~{current_segment_char_count} chars, {len(current_segment_items)} items.")
                current_segment_items = []
                current_segment_char_count = 0

            current_segment_items.append(item)
            current_segment_char_count += item_total_char_contribution

            # If a single item itself (after being added to an empty current_segment_items)
            # already exceeds the target, it forms its own segment.
            if len(current_segment_items) == 1 and current_segment_char_count > target_char_length_per_segment:
                self.logger.warning(
                    f"A single content item in '{file_name}' (type: {item.get('type')}, estimated content chars: {item_content_char_estimate}) "
                    f"with overhead results in ~{current_segment_char_count} chars, exceeding target {target_char_length_per_segment}. "
                    "It will form its own segment."
                )
                segments.append(current_segment_items)
                current_segment_items = []
                current_segment_char_count = 0

        if current_segment_items: # Add any remaining items in the last segment
            segments.append(current_segment_items)
            self.logger.debug(f"Final segment created for '{file_name}' with ~{current_segment_char_count} chars, {len(current_segment_items)} items.")

        self.logger.info(f"ContentSegmentationService: Segmented content for '{file_name}' into {len(segments)} fragments based on target char length ~{target_char_length_per_segment}.")
        return segments