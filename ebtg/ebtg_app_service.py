# ebtg/ebtg_app_service.py

import xml.etree.ElementTree as ET
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List # List 추가

# Assuming these services and DTOs are defined in the ebtg package
from .epub_processor_service import EpubProcessorService, EpubXhtmlItem # Assuming EpubXhtmlItem DTO
from .simplified_html_extractor import SimplifiedHtmlExtractor # type: ignore
from .ebtg_content_segmentation_service import ContentSegmentationService
from btg_integration.btg_integration_service import BtgIntegrationService # Corrected import
from common.progress_persistence_service import ProgressPersistenceService
from .epub_validation_service import EpubValidationService # Import EpubValidationService
from .quality_monitor_service import QualityMonitorService # Import QualityMonitorService
from .ebtg_exceptions import EbtgProcessingError, XhtmlExtractionError, ApiXhtmlGenerationError
from .config_manager import EbtgConfigManager # Assuming a config manager for EBTG

# Assuming BTG module is accessible
from btg_module.app_service import AppService as BtgAppService
from btg_module.exceptions import BtgServiceException

logger = logging.getLogger(__name__) # Or use a setup_logger like in BTG

class EbtgAppService:
    def __init__(self, config_path: Optional[str] = None):
        """
        Initializes the EBTG Application Service.

        Args:
            config_path: Path to the EBTG configuration file.
        """
        self.config_manager = EbtgConfigManager(config_path)
        self.config: Dict[str, Any] = self.config_manager.load_config()

        btg_config_path = self.config.get("btg_config_path")
        self.btg_app_service = BtgAppService(config_file_path=btg_config_path)
        
        self.epub_processor = EpubProcessorService()
        self.html_extractor = SimplifiedHtmlExtractor()
        self.content_segmenter = ContentSegmentationService()
        self.progress_service = ProgressPersistenceService()
        self.epub_validator = EpubValidationService() # Initialize EpubValidationService
        self.quality_monitor = QualityMonitorService() # Initialize QualityMonitorService
        self.btg_integration = BtgIntegrationService(
            btg_app_service=self.btg_app_service, 
            ebtg_config=self.config
        )
        
        logger.info("EbtgAppService initialized.")
        logger.info(f"EBTG Target Language: {self.config.get('target_language', 'ko')}")

    def _wrap_body_fragments_in_full_xhtml(self, body_fragments_concatenated: str, title: str, lang: str) -> str:
        """Wraps concatenated body fragments into a complete XHTML document."""
        # Ensure XML declaration is on the first line if body_content might have leading whitespace
        body_content_cleaned = body_fragments_concatenated.strip()
        return f"""<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}" lang="{lang}">
<head>
    <meta charset="utf-8"/>
    <title>{title}</title>
</head>
<body>
    {body_content_cleaned}
</body>
</html>"""

    def _is_well_formed_xml(self, xhtml_string: str) -> bool:
        """Checks if the given string is well-formed XML."""
        if not xhtml_string:
            return False
        try:
            # Attempt to parse the string as XML.
            # Add a dummy root if the content is just a fragment.
            if not xhtml_string.strip().startswith('<'):
                 # Not an XML/HTML string, or empty
                return False

            # Check for common root elements or doctype
            has_root_element = any(tag in xhtml_string for tag in ["<html>", "<body>", "<p>", "<div>"])
            is_fragment = not ("<html>" in xhtml_string and "</html>" in xhtml_string)


            if is_fragment and has_root_element:
                # For fragments, wrap in a dummy root to validate.
                # This is a basic check; more sophisticated validation might be needed.
                try:
                    ET.fromstring(f"<root>{xhtml_string}</root>")
                except ET.ParseError:
                    # If fragment parsing fails, try to see if it's a list of top-level elements
                    # by wrapping each in a dummy parent, which is not ideal.
                    # A simpler check: if it contains tags but fails wrapped, it's likely malformed.
                    if any(char in xhtml_string for char in "<>"): # Contains tag-like characters
                        logger.warning(f"Fragment XHTML is not well-formed: {xhtml_string[:100]}")
                        return False
                    else: # Plain text, not XML
                        return True # Or False, depending on strictness. Assuming plain text is not "well-formed XML".
            elif has_root_element: # Has html/body, try parsing directly
                 ET.fromstring(xhtml_string)
            else: # No common root elements, likely not structured XML/XHTML
                logger.debug(f"Content does not appear to be structured XML/XHTML: {xhtml_string[:100]}")
                return False # Or True if plain text is acceptable in some contexts. For XHTML, it's False.

            return True
        except ET.ParseError as e:
            logger.warning(f"Generated XHTML is not well-formed XML: {e}")
            logger.debug(f"Invalid XHTML (first 500 chars): {xhtml_string[:500]}")
            return False
        except Exception as ex: # Catch other potential errors during parsing
            logger.error(f"Unexpected error during XML well-formedness check: {ex}")
            logger.debug(f"Problematic XHTML (first 500 chars): {xhtml_string[:500]}")
            return False

    def _create_fallback_xhtml(self, original_xhtml_content_str: str, title: str, lang: str) -> str:
        """
        Creates a very simple XHTML document from the text content of the original XHTML.
        Images and structure (other than paragraphs) will be lost.
        """
        logger.warning(f"Creating fallback XHTML for: {title}. Structure and images will be lost.")
        try:
            # Use SimplifiedHtmlExtractor to get text items
            content_items = self.html_extractor.extract_content(original_xhtml_content_str)
            
            body_content_parts: List[str] = []
            if content_items:
                for item in content_items:
                    if item.get("type") == "text":
                        text_data = item.get("data", "")
                        if text_data.strip(): # Add non-empty text
                            body_content_parts.append(f"<p>{text_data.strip()}</p>")
            
            if not body_content_parts: # If no text items were extracted, use a placeholder
                logger.warning(f"No text content found for fallback in {title}. Using placeholder.")
                body_content_parts.append("<p>[Content could not be processed or was empty]</p>")

            fallback_body_content = "\n".join(body_content_parts)
            return self._wrap_body_fragments_in_full_xhtml(fallback_body_content, f"Fallback - {title}", lang)
        except Exception as e:
            logger.error(f"Error creating fallback XHTML for {title}: {e}", exc_info=True)
            # Super basic fallback if even text extraction fails
            return self._wrap_body_fragments_in_full_xhtml(
                "<p>[Error generating fallback content]</p>", f"Fallback Error - {title}", lang
            )

    def translate_epub(self, input_epub_path: str, output_epub_path: str) -> None:
        """
        Processes an EPUB file: extracts XHTML content, sends it for translation
        (XHTML generation) via BTG module, and reassembles the EPUB.

        Args:
            input_epub_path: Path to the input EPUB file.
            output_epub_path: Path to save the translated EPUB file.
        """
        logger.info(f"Starting EPUB translation for: {input_epub_path}")
        Path(output_epub_path).parent.mkdir(parents=True, exist_ok=True)

        try:
            # Clear any previous progress for this specific input EPUB if starting fresh,
            # or load existing progress if implementing resume functionality (future).
            self.progress_service.clear_progress(Path(input_epub_path).name)
            self.epub_processor.open_epub(input_epub_path)
            xhtml_items: list[EpubXhtmlItem] = self.epub_processor.get_xhtml_items()
            
            total_files = len(xhtml_items)
            processed_files = 0
            files_with_errors = 0

            logger.info(f"Found {total_files} XHTML files to process.")

            target_language = self.config.get("target_language", "ko")
            # Get base prompts from EBTG config (user can customize these in ebtg_config.json)
            base_prompt_for_full_doc = self.config.get(
                "prompt_instructions_for_xhtml_generation",
                # Default prompt if not in config (though EbtgConfigManager should provide one)
                "Translate the following text blocks and integrate the image information to create a complete and valid XHTML document. Preserve image sources and translate alt text. Wrap paragraphs in <p> tags."
            )
            base_prompt_for_fragment = self.config.get(
                "prompt_instructions_for_xhtml_fragment_generation",
                # Default prompt
                "You are generating a fragment of a larger XHTML document. Based on the overall task: '{overall_task_description}'. Now, translate the following text blocks and integrate the image information to create XHTML body content. Preserve image sources and translate alt text if present. Wrap paragraphs in <p> tags. Do NOT include html, head, or body tags. Ensure correct relative order of items. The items are:"
            )
            xhtml_segment_target_chars = self.config.get("xhtml_segment_target_chars", 15000) # New parameter


            for xhtml_item in xhtml_items:
                processed_files += 1
                item_filename = xhtml_item.filename
                item_id = xhtml_item.item_id
                original_xhtml_content_str: str = ""
                generated_xhtml_for_item_successfully = False

                logger.info(f"Processing file {processed_files}/{total_files}: {item_filename}")

                try:
                    original_xhtml_content_str = xhtml_item.original_content_bytes.decode('utf-8', errors='replace')
                    
                    content_items = self.html_extractor.extract_content(original_xhtml_content_str)

                    if not content_items:
                        logger.warning(f"No content items extracted from {item_filename}. Keeping original content.")
                        self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "skipped_empty_content")
                        continue

                    # Segment the content items
                    item_segments = self.content_segmenter.segment_content_items(
                        content_items, item_filename, xhtml_segment_target_chars # Use new parameter
                    )

                    final_xhtml_parts = []
                    segment_has_errors = False

                    if not item_segments: # Should not happen if content_items was not empty
                        logger.warning(f"Content segmentation returned no segments for {item_filename}. Keeping original.")
                        self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "skipped_no_segments")
                        continue

                    for i, segment_items in enumerate(item_segments):
                        # Determine segment ID and prompt based on whether it's a fragment or full doc
                        segment_id_prefix: str
                        current_prompt_instructions: str
                        is_fragment = len(item_segments) > 1

                        if is_fragment:
                            segment_id_prefix = f"{Path(item_filename).stem}_part_{i+1}{Path(item_filename).suffix}"
                            current_prompt_instructions = base_prompt_for_fragment.replace(
                                "{overall_task_description}", base_prompt_for_full_doc
                            )
                        else:
                            segment_id_prefix = item_filename
                            current_prompt_instructions = base_prompt_for_full_doc
                        
                        logger.info(f"Requesting XHTML for {'fragment' if is_fragment else 'document'}: {segment_id_prefix} ({len(segment_items)} items)")
                        
                        generated_segment_xhtml_str = self.btg_integration.generate_xhtml(
                            id_prefix=segment_id_prefix,
                            content_items=segment_items,
                            target_language=target_language,
                            prompt_instructions=current_prompt_instructions # Pass the determined prompt
                        )

                        if generated_segment_xhtml_str:
                            # Basic validation for the generated fragment/document
                            # Use QualityMonitorService for validation
                            is_valid_segment, validation_errors = self.quality_monitor.validate_xhtml_structure(
                                generated_segment_xhtml_str, segment_id_prefix
                            )
                            if is_valid_segment:
                                logger.info(f"Successfully generated and validated XHTML segment: {segment_id_prefix}.")
                                final_xhtml_parts.append(generated_segment_xhtml_str)
                            else:
                                logger.error(f"Generated XHTML segment {segment_id_prefix} is not well-formed. Errors: {validation_errors}. This part will be problematic.")
                                # Depending on strictness, could mark as error or try to use it anyway if it's a fragment
                                final_xhtml_parts.append(f"<!-- MALFORMED FRAGMENT: {segment_id_prefix} -->") # Or skip
                                segment_has_errors = True # Mark that this segment had issues
                                # break # Option: stop processing further segments for this item on first error
                            
                            # Content omission check for the segment (optional, might be too granular)
                            # _, omission_warnings_segment = self.quality_monitor.check_content_omission(segment_items, generated_segment_xhtml_str, segment_id_prefix)
                            # if omission_warnings_segment:
                            #    logger.warning(f"Segment {segment_id_prefix} - potential content omissions: {omission_warnings_segment}")
                        
                        else:
                            logger.error(f"Failed to generate XHTML for segment {segment_id_prefix}. This part will be missing.")
                            segment_has_errors = True
                            break 

                    if segment_has_errors:
                        logger.error(f"Due to errors in one or more segments, fallback content will be generated for {item_filename}.")
                        fallback_xhtml = self._create_fallback_xhtml(original_xhtml_content_str, Path(item_filename).stem, target_language)
                        self.epub_processor.update_xhtml_content(item_id, fallback_xhtml.encode('utf-8'))
                        self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "failed_segment_processing_fallback", "Error during segment processing, used fallback.")
                        files_with_errors += 1
                        continue 

                    if not final_xhtml_parts:
                        logger.warning(f"No XHTML parts generated for {item_filename} after segmentation. Using fallback.")
                        fallback_xhtml = self._create_fallback_xhtml(original_xhtml_content_str, Path(item_filename).stem, target_language)
                        self.epub_processor.update_xhtml_content(item_id, fallback_xhtml.encode('utf-8'))
                        self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "failed_no_parts_generated_fallback")
                        files_with_errors += 1
                        continue

                    final_generated_xhtml_for_item: str
                    if len(item_segments) > 1: # If it was processed in fragments
                        concatenated_body_content = "\n".join(final_xhtml_parts)
                        final_generated_xhtml_for_item = self._wrap_body_fragments_in_full_xhtml(
                            concatenated_body_content, Path(item_filename).stem, target_language
                        )
                        logger.info(f"Assembled {len(item_segments)} fragments into a full XHTML for {item_filename}.")
                    else: # Processed as a single document
                        final_generated_xhtml_for_item = final_xhtml_parts[0]

                    if not self._is_well_formed_xml(final_generated_xhtml_for_item):
                        logger.error(f"Final assembled XHTML for {item_filename} is not well-formed. Using fallback content.")
                        fallback_xhtml = self._create_fallback_xhtml(original_xhtml_content_str, Path(item_filename).stem, target_language)
                        self.epub_processor.update_xhtml_content(item_id, fallback_xhtml.encode('utf-8'))
                        self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "failed_final_validation_fallback", "Final generated content is not well-formed XML.")
                        files_with_errors += 1
                        continue
                    self.epub_processor.update_xhtml_content(item_id, final_generated_xhtml_for_item.encode('utf-8'))
                    self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "success")
                    generated_xhtml_for_item_successfully = True

                except (XhtmlExtractionError, ApiXhtmlGenerationError, BtgServiceException, UnicodeDecodeError) as e_proc:
                    logger.error(f"Processing error for {item_filename}: {e_proc}. Using fallback content.")
                    fallback_xhtml = self._create_fallback_xhtml(original_xhtml_content_str, Path(item_filename).stem, target_language)
                    self.epub_processor.update_xhtml_content(item_id, fallback_xhtml.encode('utf-8'))
                    self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, f"failed_{type(e_proc).__name__}_fallback", str(e_proc))
                    files_with_errors += 1
                except Exception as e_unexpected:
                    logger.error(f"Unexpected error processing {item_filename}: {e_unexpected}. Using fallback content.", exc_info=True)
                    fallback_xhtml = self._create_fallback_xhtml(original_xhtml_content_str, Path(item_filename).stem, target_language)
                    self.epub_processor.update_xhtml_content(item_id, fallback_xhtml.encode('utf-8'))
                    self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "failed_unexpected_fallback", str(e_unexpected))
                    files_with_errors += 1
            
            logger.info("All XHTML files processed. Saving new EPUB...")
            self.epub_processor.save_epub(output_epub_path)
            self.progress_service.save_progress(output_epub_path) # Save all accumulated progress
            logger.info(f"Translated EPUB saved to: {output_epub_path}")

            # --- IV. EpubValidationService Integration ---
            if self.config.get("perform_epub_validation", True):
                logger.info(f"Performing EPUB validation for {output_epub_path}...")
                is_valid_epub, epub_errors, epub_warnings = self.epub_validator.validate_epub(output_epub_path)
                if is_valid_epub:
                    logger.info(f"EPUB validation successful for {output_epub_path}.")
                    if epub_warnings:
                        logger.warning(f"EPUB validation for {output_epub_path} has {len(epub_warnings)} warning(s):")
                        for warn_idx, warn_msg in enumerate(epub_warnings[:5]): # Log first 5 warnings
                            logger.warning(f"  Warn {warn_idx+1}: {warn_msg}")
                else:
                    logger.error(f"EPUB validation failed for {output_epub_path} with {len(epub_errors)} error(s):")
                    for err_idx, err_msg in enumerate(epub_errors[:5]): # Log first 5 errors
                        logger.error(f"  Error {err_idx+1}: {err_msg}")
            # --- End EpubValidationService Integration ---

            if files_with_errors > 0:
                logger.warning(f"{files_with_errors}/{total_files} files encountered errors and fallback content was used.")

        except FileNotFoundError as e:
            logger.error(f"Input EPUB file not found: {input_epub_path} - {e}")
            raise EbtgProcessingError(f"Input EPUB not found: {input_epub_path}") from e
        except Exception as e:
            logger.error(f"An error occurred during EPUB translation: {e}", exc_info=True)
            self.progress_service.save_progress(output_epub_path) # Attempt to save progress even if main process fails
            raise EbtgProcessingError(f"EPUB translation failed: {e}") from e