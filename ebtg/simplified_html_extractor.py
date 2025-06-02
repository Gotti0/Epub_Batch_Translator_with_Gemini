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
                    text = element.string.strip()
                    if text:
                        current_text_parts.append(text)
                elif isinstance(element, Tag):
                    if element.name == 'img':
                        if current_text_parts:
                            content_items.append({"type": "text", "data": " ".join(current_text_parts)})
                            current_text_parts = []
                        
                        src = element.get('src', '')
                        alt = element.get('alt', '')
                        if src:
                            content_items.append({
                                "type": "image",
                                "data": {"src": src, "alt": alt}
                            })
                            logger.debug(f"Extracted image: src='{src}', alt='{alt}'")
                        else:
                            logger.warning("Found <img> tag with no src attribute. Skipping.")
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