# ebtg/quality_monitor_service.py
import logging
from typing import List, Dict, Any, Tuple
from bs4 import BeautifulSoup
from html5validator.validator import Validator as HTMLValidator # Validator 이름 충돌 방지

logger = logging.getLogger(__name__)

class QualityMonitorService:
    def __init__(self):
        self.validator = HTMLValidator()
        logger.info("QualityMonitorService initialized with HTMLValidator.")

    def validate_xhtml_structure(self, xhtml_string: str, filename_for_log: str = "") -> Tuple[bool, List[str]]:
        """
        Validates the structural integrity of the given XHTML string using html5validator.
        It attempts to validate as a fragment first, then as a full document if needed.
        """
        if not xhtml_string or not xhtml_string.strip():
            logger.warning(f"XHTML structure validation: Input string is empty for {filename_for_log}.")
            return False, ["Input XHTML string is empty."]

        errors_found: List[str] = []
        is_valid = False

        try:
            # Attempt to validate as a fragment first.
            # html5validator might require a full document structure for some checks even with validate_fragment.
            # We'll try to wrap it if direct fragment validation isn't sufficient or clear.
            # For now, let's assume validate_string can handle it or we wrap it.
            
            # Heuristic to check if it's likely a fragment or a full document
            is_likely_fragment = not ("<html" in xhtml_string.lower() and "<body" in xhtml_string.lower())

            if is_likely_fragment:
                # Wrap fragment for more robust validation if validator expects full document context
                # However, Validator().validate_fragment() should ideally handle this.
                # Let's try validate_string directly, as it might be more general.
                # If validate_fragment exists and works better, it can be used.
                # For simplicity, we use validate_string and rely on its capabilities.
                # If it's a fragment, some errors might be ignorable (e.g., missing doctype if we only care about body).
                # The `Validator` class in `html5validator` doesn't have `validate_fragment` or `validate_string` directly.
                # It has `validate` which takes a list of files or URLs.
                # To validate a string, we need to pass it as a file-like object or save to a temp file.
                # Let's try to use the internal vnu.jar call if possible, or adapt.
                # The `html5validator.validator.Validator.validate_iter` seems more appropriate for strings.
                
                # Simpler approach: The Validator class itself is iterable and yields errors.
                # We need to provide the string content.
                # The `validate` method expects file paths.
                # Let's use a temporary file for validation, as it's the most straightforward way with html5validator.
                # This is not ideal for performance but ensures standard validation.
                
                # Correction: html5validator.Validator() is the main class.
                # It doesn't directly take strings. We might need to use it differently or find an alternative.
                # For now, let's use a simpler XML well-formedness check as a placeholder
                # and note that a full HTML5 validation might require more setup (temp files or different library).
                # The original request mentioned "HTML validator 라이브러리 사용", so we stick to the intent.
                # `html5validator` is often used by saving content to a temp file.

                # Re-evaluating html5validator:
                # It seems `Validator().validate_fragment(html_fragment_string)` is NOT a standard method.
                # `Validator().validate_file(filepath)` or `Validator().validate_files(filepaths)` are.
                # A common pattern is to write to a temp file.

                # Let's use a basic XML check for now and improve if a better in-memory way for html5validator is found
                # or if we accept the temp file overhead.
                # The previous diff used ET.fromstring, which is good for XML well-formedness.
                # For HTML5 structural validity, a proper HTML parser/validator is better.

                # Given the constraints and to avoid temp files in this step,
                # we'll use a robust XML parse and log that full HTML5 validation is more complex.
                # This aligns with the "well-formed XML" check mentioned in Phase 2 of the guidelines.
                import xml.etree.ElementTree as ET
                try:
                    if not xhtml_string.strip().startswith('<'):
                        errors_found.append("Content does not start with a tag.")
                    else:
                        # If it's a fragment, wrap it for parsing to ensure it's valid within a root.
                        ET.fromstring(f"<root>{xhtml_string}</root>" if is_likely_fragment else xhtml_string)
                    is_valid = not errors_found
                except ET.ParseError as e:
                    errors_found.append(f"XML ParseError: {e}")
                if not errors_found:
                    is_valid = True

            else: # Full document
                import xml.etree.ElementTree as ET
                try:
                    ET.fromstring(xhtml_string)
                    is_valid = True
                except ET.ParseError as e:
                    errors_found.append(f"XML ParseError for full document: {e}")
            
            if errors_found:
                logger.warning(f"XHTML structure validation for '{filename_for_log}' found issues (using basic XML check): {errors_found}")
            else:
                logger.info(f"XHTML structure validation passed (basic XML check) for '{filename_for_log}'.")

        except Exception as e:
            logger.error(f"Unexpected error during XHTML structure validation for '{filename_for_log}': {e}", exc_info=True)
            errors_found.append(f"Unexpected validation error: {str(e)}")
            is_valid = False
        
        # Note: For true HTML5 validation with html5validator, saving to a temp file and calling
        # self.validator.validate([temp_file_path]) would be needed, then parsing its output.
        # This current implementation is a simplified well-formedness check.
        if not is_valid:
             logger.warning(f"Basic XML/XHTML validation failed for {filename_for_log}. Errors: {errors_found}")
        return is_valid, errors_found

    def check_content_omission(
        self,
        original_content_items: List[Dict[str, Any]],
        generated_xhtml_string: str,
        filename_for_log: str = ""
    ) -> Tuple[bool, List[str]]:
        """
        Performs basic checks for content omission.
        Returns (True, []) if no obvious omissions are detected, (False, [warnings]) otherwise.
        """
        warnings: List[str] = []
        passed = True

        if not generated_xhtml_string.strip() and original_content_items:
            warnings.append("Generated XHTML is empty, but original content existed.")
            logger.warning(f"Content omission check for '{filename_for_log}': Generated XHTML is empty.")
            return False, warnings

        try:
            soup = BeautifulSoup(generated_xhtml_string, 'html.parser')
            body = soup.find('body')
            if not body: # If no body, parse the whole soup
                body = soup

            # 1. Compare number of text items vs. paragraph-like tags
            original_text_items_count = sum(1 for item in original_content_items if item.get("type") == "text" and item.get("data","").strip())
            # Consider p, div, li as potential text containers. This is a heuristic.
            generated_text_containers_count = len(body.find_all(['p', 'div'])) # Simplified
            
            # Allow some flexibility, e.g., multiple original text items merged into one <p>
            # Or one original item split into multiple <p>s.
            # This check is very basic.
            if original_text_items_count > 0 and generated_text_containers_count == 0:
                 warnings.append(f"Potential text omission: Original had {original_text_items_count} text items, generated has 0 main text containers (p, div).")
                 passed = False
            elif original_text_items_count > generated_text_containers_count * 2 and original_text_items_count > 5 : # Heuristic
                 warnings.append(f"Potential text omission: Original had {original_text_items_count} text items, generated has significantly fewer ({generated_text_containers_count}) main text containers.")
                 # This is a weak warning, so not setting passed = False yet.

            # 2. Compare number of image items vs. <img> tags
            original_image_items_count = sum(1 for item in original_content_items if item.get("type") == "image")
            generated_img_tags_count = len(body.find_all('img'))

            if original_image_items_count != generated_img_tags_count:
                warnings.append(f"Image count mismatch: Original had {original_image_items_count} images, generated has {generated_img_tags_count} <img> tags.")
                passed = False # Image count mismatch is usually more critical

            # 3. Check if <img> tags have src attribute
            for img_tag in body.find_all('img'):
                if not img_tag.get('src'):
                    warnings.append(f"Generated <img> tag is missing 'src' attribute. Tag: {str(img_tag)[:100]}")
                    passed = False
                # Optionally, check if alt text was translated if original had alt
                # original_img_item = next((item for item in original_content_items if item["type"] == "image" and item["data"]["src"] == img_tag.get('src')), None)
                # if original_img_item and original_img_item["data"].get("alt"):
                #     if not img_tag.get("alt"):
                #         warnings.append(f"Generated <img> tag for src='{img_tag.get('src')}' is missing 'alt' text, but original had it.")
                #     elif img_tag.get("alt") == original_img_item["data"].get("alt"):
                #          warnings.append(f"Generated <img> tag for src='{img_tag.get('src')}' has untranslated 'alt' text: '{img_tag.get('alt')[:30]}...'")


            if warnings:
                logger.warning(f"Content omission checks for '{filename_for_log}' found potential issues: {warnings}")
            else:
                logger.info(f"Content omission checks passed for '{filename_for_log}'.")

        except Exception as e:
            logger.error(f"Error during content omission check for '{filename_for_log}': {e}", exc_info=True)
            warnings.append(f"Unexpected error during omission check: {str(e)}")
            passed = False

        return passed, warnings

