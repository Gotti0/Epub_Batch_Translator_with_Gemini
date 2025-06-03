# ebtg/simplified_html_extractor.py
import logging
from typing import List, Dict, Any, Union # Union 추가
from bs4 import BeautifulSoup, NavigableString, Tag
import time # Added for delay

# 새로운 아키텍처를 위한 DTO 임포트
from .ebtg_dtos import TextBlock, ImageInfo, ExtractedContentElement
from .ebtg_exceptions import XhtmlExtractionError # 예외 클래스 임포트

logger = logging.getLogger(__name__)

class SimplifiedHtmlExtractor:
    def __init__(self):
        # Optional: Make delay parameters configurable via __init__
        # self.delay_interval_elements = 100  # Add delay every N elements
        # self.delay_seconds = 0.001          # Delay duration
        pass # type: ignore
    
    def extract_content(self, xhtml_string: str) -> List[ExtractedContentElement]:
        logger.debug("Starting XHTML content extraction.")
        content_items: List[ExtractedContentElement] = []
        
        if not xhtml_string.strip():
            logger.warning("Input XHTML string is empty or whitespace only.")
            return content_items
        try:
            soup = BeautifulSoup(xhtml_string, 'html.parser')
            body = soup.find('body')
            if not body:
                logger.warning("No <body> tag found in XHTML. Processing entire document as body content.")
                body = soup # Fallback to process the whole soup object

            current_text_parts: List[str] = []

            # --- Parameters for adding a small delay ---
            # This is a palliative measure. Consider profiling for the true bottleneck.
            # If logs are very verbose (like DEBUG), reducing log level might be more effective.
            elements_processed_since_last_delay = 0
            DELAY_EVERY_N_ELEMENTS = 200  # Add a delay every 200 elements processed
            DELAY_SECONDS = 0.1  # 1 millisecond delay



            for element in body.descendants:
                elements_processed_since_last_delay += 1
                if elements_processed_since_last_delay >= DELAY_EVERY_N_ELEMENTS:
                    time.sleep(DELAY_SECONDS)
                    elements_processed_since_last_delay = 0
                if isinstance(element, NavigableString):
                    text_content = element.string
                    if text_content:
                        stripped_text = text_content.strip()
                        if stripped_text:
                            current_text_parts.append(stripped_text)
                elif isinstance(element, Tag):
                    if element.name == 'img':
                        if current_text_parts:
                            full_text_before = " ".join(current_text_parts)
                            content_items.append(TextBlock(text_content=full_text_before)) # 로그 제거
                            # logger.debug(f"Extracted text block (before image): '{full_text_before[:50]}...'")
                            current_text_parts = []
                        
                        src = element.get('src', '')
                        alt = element.get('alt', '')
                        original_tag_string = str(element)
                        if src:
                            image_info = ImageInfo(
                                original_tag_string=original_tag_string,
                                src=src,
                                original_alt=alt
                            )
                            content_items.append(image_info)
                            # logger.debug(f"Extracted image: src='{src}', alt='{alt}'") # 로그 제거
                        else:
                            logger.warning("Found <img> tag with no src attribute. Skipping image item, but processed preceding text if any.")
                    # Block-level or significant separator tags that should finalize any pending text.
                    elif element.name in ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'br', 'hr', 'table', 'ul', 'ol', 'dl', 'blockquote', 'pre', 'figure', 'figcaption']:
                        if current_text_parts:
                            text_block_content = " ".join(current_text_parts)
                            content_items.append(TextBlock(text_content=text_block_content)) # 로그 제거
                            # logger.debug(f"Extracted text block (due to separator tag '{element.name}'): '{text_block_content[:50]}...'")
                            current_text_parts = []

            if current_text_parts:
                final_text_block_content = " ".join(current_text_parts)
                content_items.append(TextBlock(text_content=final_text_block_content))
                # logger.debug(f"Extracted final text block: '{final_text_block_content[:50]}...'") # 루프 후 발생하는 로그이므로 유지하거나, 필요시 제거 가능. 여기서는 일관성을 위해 제거.

        except Exception as e:
            logger.error(f"Error during HTML parsing or extraction: {e}", exc_info=True)
            raise XhtmlExtractionError(f"Failed to extract content: {e}") from e
            
        if not content_items and xhtml_string.strip():
            if body and not content_items and body.string and body.string.strip():
                 text_directly_in_body = body.string.strip()
                 content_items.append(TextBlock(text_content=text_directly_in_body))
                 logger.debug(f"Extracted text directly from body: '{text_directly_in_body[:50]}...'")

        logger.debug(f"Extracted {len(content_items)} content items.")
        return content_items