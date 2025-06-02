# c:\Users\Hyunwoo_Room\Downloads\EBTG_Project\ebtg\ebtg_simplified_html_extractor.py
from typing import List, Dict, Any
from bs4 import BeautifulSoup, NavigableString, Tag

from .ebtg_logger import EbtgLogger # Assuming EbtgLogger is in ebtg_logger.py
from .ebtg_exceptions import XhtmlExtractionError

class SimplifiedHtmlExtractor:
    """
    Extracts text blocks and image information sequentially from XHTML content.
    This extractor aims for simplicity, focusing on content order rather than
    deep structural analysis, aligning with the v7 architecture's goal of
    API-driven XHTML generation.
    """

    # Tags whose content (and their own presence) should generally be ignored for direct text extraction.
    # Text within these tags will not be collected.
    IGNORE_TAGS = {'script', 'style', 'meta', 'link', 'title', 'head', 'noscript', 'object', 'embed', 'applet', 'iframe'}

    def __init__(self, logger: EbtgLogger):
        self.logger = logger

    def _flush_text_buffer(self, text_buffer: List[str], content_items: List[Dict[str, Any]]):
        """
        Joins collected text parts, normalizes whitespace, and adds to content_items if not empty.
        """
        if text_buffer:
            # Join all parts, then strip leading/trailing whitespace from the combined string
            full_text = "".join(text_buffer).strip()
            # Normalize internal whitespace (e.g., multiple spaces/newlines to a single space)
            full_text = " ".join(full_text.split())
            if full_text:
                content_items.append({"type": "text", "data": full_text})
            text_buffer.clear()

    def extract_content(self, xhtml_content: str, file_name: str) -> List[Dict[str, Any]]:
        """
        Parses XHTML content and extracts a list of text and image items.

        Args:
            xhtml_content: The XHTML string to parse.
            file_name: The name of the file being processed (for logging).

        Returns:
            A list of dictionaries, e.g.:
            [
                {"type": "text", "data": "Some text..."},
                {"type": "image", "data": {"src": "path/to/img.png", "alt": "Alt text"}},
                ...
            ]

        Raises:
            XhtmlExtractionError: If BeautifulSoup parsing fails.
        """
        self.logger.log_debug(f"SimplifiedHtmlExtractor: Starting extraction for '{file_name}'")
        content_items: List[Dict[str, Any]] = []
        text_buffer: List[str] = []

        try:
            # Using 'html.parser' as it's generally robust.
            # For strict XHTML, 'xml' or 'lxml-xml' could be used, but 'html.parser'
            # is more forgiving of minor issues often found in EPUBs.
            soup = BeautifulSoup(xhtml_content, 'html.parser')
        except Exception as e:
            self.logger.log_error(f"BeautifulSoup parsing failed for '{file_name}': {e}", exc_info=True)
            raise XhtmlExtractionError(
                f"Failed to parse XHTML content in '{file_name}' using BeautifulSoup.",
                original_exception=e,
                details={"filename": file_name}
            )

        body = soup.body
        if not body:
            self.logger.log_warning(f"No <body> tag found in '{file_name}'. Attempting to process root elements.")
            # If no body, iterate over the top-level elements of the soup.
            # This is a fallback; well-formed XHTML for EPUBs should have a body.
            elements_to_process = soup.children
        else:
            elements_to_process = body.descendants

        for element in elements_to_process:
            if isinstance(element, Tag):
                if element.name in self.IGNORE_TAGS:
                    # Effectively prune the traversal for these tags' content
                    # by clearing their contents if we want to be very strict.
                    # However, `descendants` will still yield children unless we skip.
                    # The NavigableString check below handles not adding their text.
                    # For now, we ensure their direct NavigableString children are skipped.
                    # If an IGNORE_TAG contains other meaningful tags (unlikely for script/style),
                    # this logic might need adjustment. For now, this is simple.
                    continue # Skip processing the tag itself and its descendants will be checked

                if element.name == 'img':
                    self._flush_text_buffer(text_buffer, content_items)
                    src = element.get('src')
                    alt = element.get('alt')

                    if not src:
                        self.logger.log_warning(f"Image tag in '{file_name}' found without a 'src' attribute. Skipping image: {element}")
                        continue
                    
                    content_items.append({
                        "type": "image",
                        "data": {
                            "src": src,
                            "alt": alt if alt is not None else "" # Ensure alt is always a string
                        }
                    })
                elif element.name == 'br':
                    # A <br> tag explicitly breaks a line.
                    # Treat as the end of a text block.
                    self._flush_text_buffer(text_buffer, content_items)

            elif isinstance(element, NavigableString):
                # Check if the parent tag is one of the ignored types
                parent_tag_name = element.parent.name if hasattr(element.parent, 'name') else None
                if parent_tag_name and parent_tag_name in self.IGNORE_TAGS:
                    continue # Skip text from ignored tags

                text = str(element) # Don't strip here, preserve spaces for joining
                                    # Stripping will happen in _flush_text_buffer after join
                if text.strip(): # Only add if the string is not just whitespace
                    text_buffer.append(text)
        
        # After iterating through all relevant elements, flush any remaining text.
        self._flush_text_buffer(text_buffer, content_items)

        self.logger.log_info(f"SimplifiedHtmlExtractor: Extracted {len(content_items)} items from '{file_name}'.")
        return content_items

if __name__ == '__main__':
    # Example Usage (requires a dummy logger for testing)
    class DummyLogger:
        def log_debug(self, msg): print(f"DEBUG: {msg}")
        def log_info(self, msg): print(f"INFO: {msg}")
        def log_warning(self, msg): print(f"WARNING: {msg}")
        def log_error(self, msg, exc_info=False): print(f"ERROR: {msg}")

    logger = DummyLogger()
    extractor = SimplifiedHtmlExtractor(logger)

    sample_xhtml_1 = """
    <html>
        <head><title>Test</title></head>
        <body>
            <p>This is the <strong>first</strong> paragraph. It has some  ведущий text.</p>
            <img src="image1.png" alt="Alt text for image 1"/>
            Some text directly under body.
            <div>
                Another paragraph <img src="images/image2.jpg" alt="Alt text for image 2"/> inside a div.
                And more text here. <br/> Followed by text after the break.
            </div>
            Final text.
            <script>console.log("This should be ignored");</script>
            <style>.dummy { color: red; }</style>
        </body>
    </html>
    """
    print("\n--- Test Case 1 ---")
    items1 = extractor.extract_content(sample_xhtml_1, "sample1.xhtml")
    for i, item in enumerate(items1):
        print(f"{i+1}: {item}")

    sample_xhtml_2 = """
    <body>
        Text before image. <img src="img.gif" alt="A GIF"> Text after image.
        <p>New paragraph.</p>
        Text with no parent p tag.
    </body>
    """
    print("\n--- Test Case 2 ---")
    items2 = extractor.extract_content(sample_xhtml_2, "sample2.xhtml")
    for i, item in enumerate(items2):
        print(f"{i+1}: {item}")

    sample_xhtml_no_body = "<p>Just a paragraph.</p><img src='test.jpg'/>"
    print("\n--- Test Case 3 (No Body) ---")
    items3 = extractor.extract_content(sample_xhtml_no_body, "sample_no_body.xhtml")
    for i, item in enumerate(items3):
        print(f"{i+1}: {item}")
    
    sample_xhtml_empty_alt = """
    <body><img src="empty_alt.png" alt=""> Text after.</body>
    """
    print("\n--- Test Case 4 (Empty Alt) ---")
    items4 = extractor.extract_content(sample_xhtml_empty_alt, "sample_empty_alt.xhtml")
    for i, item in enumerate(items4):
        print(f"{i+1}: {item}")

    sample_xhtml_no_alt = """
    <body><img src="no_alt.png"> Text after no alt.</body>
    """
    print("\n--- Test Case 5 (No Alt Attribute) ---")
    items5 = extractor.extract_content(sample_xhtml_no_alt, "sample_no_alt.xhtml")
    for i, item in enumerate(items5):
        print(f"{i+1}: {item}")

    sample_xhtml_no_src = """
    <body><img alt="This image has no src"> Text after no src.</body>
    """
    print("\n--- Test Case 6 (No Src Attribute) ---")
    items6 = extractor.extract_content(sample_xhtml_no_src, "sample_no_src.xhtml")
    for i, item in enumerate(items6):
        print(f"{i+1}: {item}")

    sample_xhtml_script_content = """
    <body>
    Text before script.
    <script type="text/javascript">
        var x = "hello"; // this is javascript
    </script>
    Text after script.
    </body>
    """
    print("\n--- Test Case 7 (Script Content) ---")
    items7 = extractor.extract_content(sample_xhtml_script_content, "sample_script.xhtml")
    for i, item in enumerate(items7):
        print(f"{i+1}: {item}")
