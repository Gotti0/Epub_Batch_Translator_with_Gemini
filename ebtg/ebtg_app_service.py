# ebtg/ebtg_app_service.py

import xml.etree.ElementTree as ET
import logging
from pathlib import Path
from typing import Dict, Any, Optional

# Assuming these services and DTOs are defined in the ebtg package
from .epub_processor_service import EpubProcessorService, EpubXhtmlItem # Assuming EpubXhtmlItem DTO
from .simplified_html_extractor import SimplifiedHtmlExtractor # type: ignore
from .ebtg_content_segmentation_service import ContentSegmentationService
from btg_integration.btg_integration_service import BtgIntegrationService # Corrected import
from common.progress_persistence_service import ProgressPersistenceService
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
            ET.fromstring(xhtml_string)
            return True
        except ET.ParseError as e:
            logger.warning(f"Generated XHTML is not well-formed XML: {e}")
            logger.debug(f"Invalid XHTML (first 500 chars): {xhtml_string[:500]}")
            return False

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
            base_prompt_for_full_doc = self.config.get(
                "prompt_instructions_for_xhtml_generation",
                "Translate the following text blocks and integrate the image information to create a complete and valid XHTML document. Preserve image sources and translate alt text. Wrap paragraphs in <p> tags."
            )
            base_prompt_for_fragment = self.config.get(
                "prompt_instructions_for_xhtml_fragment_generation",
                "You are generating a fragment of a larger XHTML document. Based on the overall task: '{overall_task_description}'. Now, translate the following text blocks and integrate the image information to create XHTML body content. Preserve image sources and translate alt text if present. Wrap paragraphs in <p> tags. Do NOT include html, head, or body tags. Ensure correct relative order of items. The items are:"
            )
            max_items_per_segment = self.config.get("content_segmentation_max_items", 0)


            for xhtml_item in xhtml_items:
                processed_files += 1
                item_filename = xhtml_item.filename
                item_id = xhtml_item.item_id
                original_xhtml_content_str: str = ""

                logger.info(f"Processing file {processed_files}/{total_files}: {item_filename}")

                try:
                    original_xhtml_content_str = xhtml_item.original_content_bytes.decode('utf-8', errors='replace')
                    
                    content_items = self.html_extractor.extract_content(original_xhtml_content_str)

                    if not content_items:
                        logger.warning(f"No content items extracted from {item_filename}. Keeping original content.")
                        # self.epub_processor.update_xhtml_content(item_id, xhtml_item.original_content_bytes) # Already default
                        self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "skipped_empty_content")
                        continue

                    # Segment the content items
                    item_segments = self.content_segmenter.segment_content_items(
                        content_items, item_filename, max_items_per_segment
                    )

                    final_xhtml_parts = []
                    segment_has_errors = False

                    if not item_segments: # Should not happen if content_items was not empty
                        logger.warning(f"Content segmentation returned no segments for {item_filename}. Keeping original.")
                        self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "skipped_no_segments")
                        continue

                    for i, segment_items in enumerate(item_segments):
                        segment_id_prefix = f"{Path(item_filename).stem}_part_{i+1}{Path(item_filename).suffix}" if len(item_segments) > 1 else item_filename
                        
                        current_prompt_instructions: str
                        if len(item_segments) > 1:
                            current_prompt_instructions = base_prompt_for_fragment.replace(
                                "{overall_task_description}", base_prompt_for_full_doc
                            )
                        else:
                            current_prompt_instructions = base_prompt_for_full_doc

                        logger.info(f"Requesting XHTML for segment: {segment_id_prefix} ({len(segment_items)} items)")
                        
                        generated_segment_xhtml_str = self.btg_integration.generate_xhtml(
                            id_prefix=segment_id_prefix,
                            content_items=segment_items,
                            target_language=target_language,
                            prompt_instructions=current_prompt_instructions
                        )

                        if generated_segment_xhtml_str:
                            logger.info(f"Successfully generated XHTML for segment {segment_id_prefix}.")
                            final_xhtml_parts.append(generated_segment_xhtml_str)
                        else:
                            logger.error(f"Failed to generate XHTML for segment {segment_id_prefix}. This part will be missing.")
                            segment_has_errors = True
                            break 

                    if segment_has_errors:
                        logger.error(f"Due to errors in one or more segments, original content will be kept for {item_filename}.")
                        self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "failed_segment_processing", "Error during segment processing.")
                        files_with_errors += 1
                        continue 

                    if not final_xhtml_parts:
                        logger.warning(f"No XHTML parts generated for {item_filename} after segmentation. Keeping original.")
                        self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "failed_no_parts_generated")
                        continue

                    final_generated_xhtml_for_item: str
                    if len(item_segments) > 1:
                        concatenated_body_content = "\n".join(final_xhtml_parts)
                        final_generated_xhtml_for_item = self._wrap_body_fragments_in_full_xhtml(
                            concatenated_body_content, Path(item_filename).stem, target_language
                        )
                        logger.info(f"Assembled {len(item_segments)} fragments into a full XHTML for {item_filename}.")
                    else:
                        final_generated_xhtml_for_item = final_xhtml_parts[0]

                    # --- Phase 2: Basic XHTML Validation ---
                    if not self._is_well_formed_xml(final_generated_xhtml_for_item):
                        logger.error(f"Generated XHTML for {item_filename} is not well-formed. Keeping original content.")
                        self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "failed_validation", "Generated content is not well-formed XML.")
                        files_with_errors += 1
                        continue # Skip updating this item
                    # --- End Phase 2 Validation ---

                    self.epub_processor.update_xhtml_content(item_id, final_generated_xhtml_for_item.encode('utf-8')) # type: ignore
                    self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "success") # type: ignore

                except XhtmlExtractionError as e:
                    logger.error(f"Error extracting content from {item_filename}: {e}. Keeping original content.")
                    self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "failed_extraction", str(e))
                    files_with_errors += 1
                except ApiXhtmlGenerationError as e:
                    logger.error(f"API error generating XHTML for {item_filename}: {e}. Keeping original content.")
                    self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "failed_api_generation", str(e))
                    files_with_errors += 1
                except BtgServiceException as e: 
                    logger.error(f"BTG Service error during processing for {item_filename}: {e}. Keeping original content.")
                    self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "failed_btg_service", str(e))
                    files_with_errors += 1
                except UnicodeDecodeError as e:
                    logger.error(f"Unicode decode error for {item_filename}: {e}. Keeping original content.")
                    self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "failed_unicode_decode", str(e))
                    files_with_errors += 1
                except Exception as e:
                    logger.error(f"Unexpected error processing {item_filename}: {e}. Keeping original content.", exc_info=True)
                    self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "failed_unexpected", str(e))
                    files_with_errors += 1
            
            logger.info("All XHTML files processed. Saving new EPUB...")
            self.epub_processor.save_epub(output_epub_path)
            self.progress_service.save_progress(output_epub_path) # Save all accumulated progress
            logger.info(f"Translated EPUB saved to: {output_epub_path}")
            if files_with_errors > 0:
                logger.warning(f"{files_with_errors}/{total_files} files encountered errors and their original content was kept.")

        except FileNotFoundError as e:
            logger.error(f"Input EPUB file not found: {input_epub_path} - {e}")
            raise EbtgProcessingError(f"Input EPUB not found: {input_epub_path}") from e
        except Exception as e:
            logger.error(f"An error occurred during EPUB translation: {e}", exc_info=True)
            self.progress_service.save_progress(output_epub_path) # Attempt to save progress even if main process fails
            raise EbtgProcessingError(f"EPUB translation failed: {e}") from e