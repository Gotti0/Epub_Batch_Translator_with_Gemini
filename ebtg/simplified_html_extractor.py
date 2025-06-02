# ebtg/simplified_html_extractor.py
import logging
from typing import List, Dict, Any
from bs4 import BeautifulSoup, NavigableString, Tag

logger = logging.getLogger(__name__)

class SimplifiedHtmlExtractor:
    def __init__(self):
        pass

    def extract_content(self, xhtml_string: str) -> List[Dict[str, Any]]:
        logger.debug("Starting XHTML content extraction.")
        content_items: List[Dict[str, Any]] = []
        
        if not xhtml_string.strip():
            logger.warning("Input XHTML string is empty or whitespace only.")
            return content_items

        try:
            soup = BeautifulSoup(xhtml_string, 'html.parser')
            body = soup.find('body')
            if not body:
                logger.warning("No <body> tag found in XHTML. Processing entire document as body content.")
                body = soup # Fallback to process the whole soup object

            current_text_parts = []

            for element in body.descendants:
                if isinstance(element, NavigableString):
                    # .string can be None if it's a comment or special string.
                    # Also, handle cases where element.string might not be a simple string.
                    text_content = element.string
                    if text_content:
                        stripped_text = text_content.strip()
                        if stripped_text:
                            current_text_parts.append(stripped_text)
                elif isinstance(element, Tag):
                    if element.name == 'img':
                        hint_before_snippet_text = None
                        if current_text_parts:
                            full_text_before = " ".join(current_text_parts)
                            content_items.append({"type": "text", "data": full_text_before})
                            # Create snippet from the text that was just added
                            hint_before_snippet_text = (full_text_before[-50:]) if len(full_text_before) > 50 else full_text_before
                            current_text_parts = [] # Reset for any text after this image
                        
                        src = element.get('src', '')
                        alt = element.get('alt', '')
                        
                        image_data_dict = {"src": src, "alt": alt}
                        if hint_before_snippet_text:
                            image_data_dict["context_before_snippet"] = hint_before_snippet_text
                        
                        # Capture hint_after_snippet
                        after_snippet_parts_list = []
                        temp_collected_chars_count = 0
                        max_snippet_chars_val = 50 # Max characters for the after snippet
                        
                        for next_element_node in element.next_elements:
                            if len(after_snippet_parts_list) > 3 or temp_collected_chars_count >= max_snippet_chars_val: # Limit number of parts or total characters
                                break
                            if isinstance(next_element_node, NavigableString):
                                text_content_piece = next_element_node.string
                                if text_content_piece:
                                    stripped_text_piece = text_content_piece.strip()
                                    if stripped_text_piece:
                                        if temp_collected_chars_count + len(stripped_text_piece) > max_snippet_chars_val:
                                            can_add_chars = max_snippet_chars_val - temp_collected_chars_count
                                            after_snippet_parts_list.append(stripped_text_piece[:can_add_chars])
                                            temp_collected_chars_count += can_add_chars
                                            break 
                                        else:
                                            after_snippet_parts_list.append(stripped_text_piece)
                                            temp_collected_chars_count += len(stripped_text_piece)
                            elif isinstance(next_element_node, Tag):
                                # If we hit another significant block or image, stop collecting snippet.
                                if next_element_node.name in ['img', 'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'br', 'hr', 'table', 'ul', 'ol', 'dl']:
                                    break 
                        
                        if after_snippet_parts_list:
                            image_data_dict["context_after_snippet"] = " ".join(after_snippet_parts_list)

                        if src:
                            content_items.append({
                                "type": "image",
                                "data": image_data_dict
                            })
                            logger.debug(f"Extracted image: {image_data_dict}")
                        else:
                            logger.warning("Found <img> tag with no src attribute. Skipping image item, but processed preceding text if any.")
                    elif element.name in ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'br', 'hr', 'table', 'ul', 'ol', 'dl']:
                        # Treat these as block-level or significant separators
                        if current_text_parts:
                            content_items.append({"type": "text", "data": " ".join(current_text_parts)})
                            current_text_parts = []
                        # For br/hr, if they are meant to create space, the LLM should infer from context.
                        # Adding empty text blocks can sometimes confuse LLMs.

            if current_text_parts:
                content_items.append({"type": "text", "data": " ".join(current_text_parts)})

        except Exception as e:
            logger.error(f"Error during HTML parsing or extraction: {e}", exc_info=True)
            from .ebtg_exceptions import XhtmlExtractionError
            raise XhtmlExtractionError(f"Failed to extract content: {e}") from e
            
        if not content_items and xhtml_string.strip():
            # If nothing was extracted but there was input, log it.
            # This might happen for very simple XHTML like "<body>Just text</body>"
            # The current logic might miss text directly in body if not in a descendant tag or NavigableString at top level of body.
            # A quick fix for text directly in body:
            if body and not content_items and body.string and body.string.strip():
                 content_items.append({"type": "text", "data": body.string.strip()})

        logger.debug(f"Extracted {len(content_items)} content items.")
        return content_items