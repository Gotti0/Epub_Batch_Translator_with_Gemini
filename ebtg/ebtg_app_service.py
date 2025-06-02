# ebtg/ebtg_app_service.py

import logging
from pathlib import Path
from typing import Dict, Any, Optional

# Assuming these services and DTOs are defined in the ebtg package
from .epub_processor_service import EpubProcessorService, EpubXhtmlItem # Assuming EpubXhtmlItem DTO
from .simplified_html_extractor import SimplifiedHtmlExtractor # type: ignore
from btg_integration.btg_integration_service import BtgIntegrationService # Corrected import
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
        self.btg_integration = BtgIntegrationService(
            btg_app_service=self.btg_app_service, 
            ebtg_config=self.config
        )
        
        logger.info("EbtgAppService initialized.")
        logger.info(f"EBTG Target Language: {self.config.get('target_language', 'ko')}")


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
            self.epub_processor.open_epub(input_epub_path)
            xhtml_items: list[EpubXhtmlItem] = self.epub_processor.get_xhtml_items()
            
            total_files = len(xhtml_items)
            processed_files = 0
            files_with_errors = 0

            logger.info(f"Found {total_files} XHTML files to process.")

            target_language = self.config.get("target_language", "ko")
            prompt_instructions = self.config.get(
                "prompt_instructions_for_xhtml_generation",
                "Translate the following text blocks and integrate the image information to create a complete and valid XHTML document. Preserve image sources and translate alt text. Wrap paragraphs in <p> tags."
            )

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
                        continue

                    id_prefix_for_btg = item_filename 

                    generated_xhtml_str = self.btg_integration.generate_xhtml(
                        id_prefix=id_prefix_for_btg,
                        content_items=content_items,
                        target_language=target_language,
                        prompt_instructions=prompt_instructions 
                    )

                    if generated_xhtml_str:
                        logger.info(f"Successfully generated XHTML for {item_filename}.")
                        self.epub_processor.update_xhtml_content(item_id, generated_xhtml_str.encode('utf-8'))
                    else:
                        logger.error(f"Failed to generate XHTML for {item_filename} (API/BTG error). Keeping original content.")
                        files_with_errors += 1

                except XhtmlExtractionError as e:
                    logger.error(f"Error extracting content from {item_filename}: {e}. Keeping original content.")
                    files_with_errors += 1
                except ApiXhtmlGenerationError as e:
                    logger.error(f"API error generating XHTML for {item_filename}: {e}. Keeping original content.")
                    files_with_errors += 1
                except BtgServiceException as e: 
                    logger.error(f"BTG Service error during processing for {item_filename}: {e}. Keeping original content.")
                    files_with_errors += 1
                except UnicodeDecodeError as e:
                    logger.error(f"Unicode decode error for {item_filename}: {e}. Keeping original content.")
                    files_with_errors += 1
                except Exception as e:
                    logger.error(f"Unexpected error processing {item_filename}: {e}. Keeping original content.", exc_info=True)
                    files_with_errors += 1
            
            logger.info("All XHTML files processed. Saving new EPUB...")
            self.epub_processor.save_epub(output_epub_path)
            logger.info(f"Translated EPUB saved to: {output_epub_path}")
            if files_with_errors > 0:
                logger.warning(f"{files_with_errors}/{total_files} files encountered errors and their original content was kept.")

        except FileNotFoundError as e:
            logger.error(f"Input EPUB file not found: {input_epub_path} - {e}")
            raise EbtgProcessingError(f"Input EPUB not found: {input_epub_path}") from e
        except Exception as e:
            logger.error(f"An error occurred during EPUB translation: {e}", exc_info=True)
            raise EbtgProcessingError(f"EPUB translation failed: {e}") from e