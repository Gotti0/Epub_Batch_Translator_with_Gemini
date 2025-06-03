# ebtg/ebtg_app_service.py

import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Tuple # List 추가, Callable 추가

# Assuming these services and DTOs are defined in the ebtg package
from .epub_processor_service import EpubProcessorService, EpubXhtmlItem # Assuming EpubXhtmlItem DTO
from bs4 import BeautifulSoup # For parsing HTML fragments
from .simplified_html_extractor import SimplifiedHtmlExtractor # type: ignore
from .ebtg_content_segmentation_service import ContentSegmentationService
from btg_integration.btg_integration_service import BtgIntegrationService # Corrected import
from common.progress_persistence_service import ProgressPersistenceService
from .epub_validation_service import EpubValidationService # Import EpubValidationService
from .quality_monitor_service import QualityMonitorService # Import QualityMonitorService
from .ebtg_exceptions import EbtgProcessingError, XhtmlExtractionError, ApiXhtmlGenerationError
from .ebtg_dtos import EpubProcessingProgressDTO, ExtractedContentElement, TextBlock, ImageInfo # DTO 추가
from .config_manager import EbtgConfigManager

# Assuming BTG module is accessible
from btg_module.app_service import AppService as BtgAppService
from btg_module.exceptions import BtgServiceException
from btg_module.dtos import LorebookEntryDTO # For EBTG-managed lorebook
from btg_module.file_handler import read_json_file as btg_read_json_file # To avoid name clash if ebtg had one
from collections import defaultdict
from .ebtg_dtos import TranslateTextChunksRequestDto, TranslateTextChunksResponseDto

# Define a unique separator for merging text chunks
EBTG_MERGE_SEPARATOR = "\n<EBTG_TEXT_SEPARATOR_DO_NOT_TRANSLATE_THIS_TAG/>\n"


@dataclass
class SegmentProcessingTask:
    xhtml_item_id: Any
    xhtml_item_filename: str
    original_xhtml_content_str: str # For fallback
    segment_items_data: List[Dict[str, Any]]
    segment_index: int
    total_segments_for_item: int
    target_language: str
    # The base prompt template for the entire item, to be adapted for fragments if necessary.
    ebtg_lorebook_context_for_segment: str # Added for pre-calculated lorebook context
    prompt_template_for_item: str

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

        # EBTG-managed lorebook
        self.ebtg_lorebook_entries: List[LorebookEntryDTO] = []
        self.ebtg_lorebook_json_path = self.config.get("ebtg_lorebook_json_path")
        self.ebtg_max_lorebook_entries_injection = self.config.get("ebtg_max_lorebook_entries_injection", 5)
        self.ebtg_max_lorebook_chars_injection = self.config.get("ebtg_max_lorebook_chars_injection", 1000)
        self._load_ebtg_lorebook_data()

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
        if self.ebtg_lorebook_entries:
            logger.info(f"EBTG Lorebook loaded with {len(self.ebtg_lorebook_entries)} entries from {self.ebtg_lorebook_json_path}")

    def _load_ebtg_lorebook_data(self):
        """Loads lorebook data for EBTG's own injection mechanism."""
        if self.ebtg_lorebook_json_path and Path(self.ebtg_lorebook_json_path).exists():
            try:
                raw_data = btg_read_json_file(self.ebtg_lorebook_json_path)
                if isinstance(raw_data, list):
                    for item_dict in raw_data:
                        if isinstance(item_dict, dict) and "keyword" in item_dict and "description" in item_dict:
                            try:
                                entry = LorebookEntryDTO(
                                    keyword=item_dict.get("keyword", ""),
                                    description=item_dict.get("description", ""),
                                    category=item_dict.get("category"),
                                    importance=int(item_dict.get("importance", 0)) if item_dict.get("importance") is not None else None,
                                    sourceSegmentTextPreview=item_dict.get("sourceSegmentTextPreview"),
                                    isSpoiler=bool(item_dict.get("isSpoiler", False)),
                                    source_language=item_dict.get("source_language")
                                )
                                if entry.keyword and entry.description:
                                    self.ebtg_lorebook_entries.append(entry)
                            except (TypeError, ValueError) as e_dto:
                                logger.warning(f"EBTG Lorebook: Error converting item to DTO: {item_dict}, Error: {e_dto}")
                logger.info(f"EBTG Lorebook: Loaded {len(self.ebtg_lorebook_entries)} entries from {self.ebtg_lorebook_json_path}")
            except Exception as e:
                logger.error(f"EBTG Lorebook: Failed to load or parse from {self.ebtg_lorebook_json_path}: {e}", exc_info=True)
        else:
            logger.info(f"EBTG Lorebook: Path '{self.ebtg_lorebook_json_path}' not configured or file does not exist. No EBTG-specific lorebook loaded.")

    def _format_ebtg_lorebook_for_prompt(self, lorebook_entries: List[LorebookEntryDTO]) -> str:
        """Formats selected EBTG lorebook entries for prompt injection."""
        if not lorebook_entries:
            return "로어북 컨텍스트 없음 (EBTG 제공)"

        selected_entries_str = []
        current_chars = 0
        entries_count = 0

        def sort_key(entry: LorebookEntryDTO):
            importance = entry.importance or 0
            if entry.isSpoiler:
                importance -= 100
            return (-importance, entry.keyword.lower())

        sorted_entries = sorted(lorebook_entries, key=sort_key)

        for entry in sorted_entries:
            if entries_count >= self.ebtg_max_lorebook_entries_injection:
                break

            details_parts = []
            if entry.category: details_parts.append(f"카테고리: {entry.category}")
            if entry.isSpoiler is not None: details_parts.append(f"스포일러: {'예' if entry.isSpoiler else '아니오'}")
            details_str = ", ".join(details_parts)
            lang_info = f" (언어: {entry.source_language})" if entry.source_language else ""
            entry_str = f"- {entry.keyword}{lang_info}: {entry.description} ({details_str})"

            if current_chars + len(entry_str) > self.ebtg_max_lorebook_chars_injection and entries_count > 0:
                break
            
            selected_entries_str.append(entry_str)
            current_chars += len(entry_str) + 1 
            entries_count += 1
        
        if not selected_entries_str:
            return "로어북 컨텍스트 없음 (EBTG 제공 - 제한으로 인해 선택된 항목 없음)"
            
        return "\n".join(selected_entries_str)

    def _get_relevant_lorebook_context_for_items(self, content_items: List[Dict[str, Any]]) -> str:
        """Filters EBTG lorebook entries based on content_items and formats them."""
        if not self.ebtg_lorebook_entries or not content_items:
            return "로어북 컨텍스트 없음 (EBTG 제공 - 로어북 비어있거나 콘텐츠 없음)"

        relevant_entries: List[LorebookEntryDTO] = []
        combined_text_for_matching = ""
        for item in content_items:
            if item.get("type") == "text" and isinstance(item.get("data"), str):
                combined_text_for_matching += item["data"].lower() + " "
            elif item.get("type") == "image" and isinstance(item.get("data"), dict) and isinstance(item["data"].get("alt"), str):
                combined_text_for_matching += item["data"]["alt"].lower() + " "
        
        if not combined_text_for_matching.strip():
            return "로어북 컨텍스트 없음 (EBTG 제공 - 콘텐츠 내 텍스트 없음)"

        for entry in self.ebtg_lorebook_entries:
            if entry.keyword.lower() in combined_text_for_matching:
                relevant_entries.append(entry)
        
        if relevant_entries:
            logger.info(f"EBTG Lorebook: Found {len(relevant_entries)} relevant entries for current content. Keywords: {[e.keyword for e in relevant_entries[:5]]}...")
            return self._format_ebtg_lorebook_for_prompt(relevant_entries)
        else:
            logger.info("EBTG Lorebook: No relevant entries found for current content.")
            return "로어북 컨텍스트 없음 (EBTG 제공 - 관련 항목 없음)"

    def _get_relevant_lorebook_context_for_extracted_elements(self, elements: List[ExtractedContentElement]) -> str:
        """Filters EBTG lorebook entries based on ExtractedContentElement list and formats them."""
        if not self.ebtg_lorebook_entries or not elements:
            return "로어북 컨텍스트 없음 (EBTG 제공 - 로어북 비어있거나 콘텐츠 없음)"

        relevant_entries: List[LorebookEntryDTO] = []
        combined_text_for_matching = ""
        for element in elements:
            if isinstance(element, TextBlock):
                combined_text_for_matching += element.text_content.lower() + " "
            elif isinstance(element, ImageInfo) and element.original_alt:
                combined_text_for_matching += element.original_alt.lower() + " "
        
        if not combined_text_for_matching.strip():
            return "로어북 컨텍스트 없음 (EBTG 제공 - 콘텐츠 내 텍스트 없음)"

        for entry in self.ebtg_lorebook_entries:
            # Using simple keyword matching. More sophisticated matching could be implemented.
            if entry.keyword.lower() in combined_text_for_matching:
                relevant_entries.append(entry)
        
        if relevant_entries:
            logger.info(f"EBTG Lorebook: Found {len(relevant_entries)} relevant entries for current extracted elements. Keywords: {[e.keyword for e in relevant_entries[:5]]}...")
            return self._format_ebtg_lorebook_for_prompt(relevant_entries)
        else:
            logger.info("EBTG Lorebook: No relevant entries found for current extracted elements.")
            return "로어북 컨텍스트 없음 (EBTG 제공 - 관련 항목 없음)"

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
                    # content_items here is List[ExtractedContentElement]
                    if isinstance(item, TextBlock):
                        text_data = item.text_content
                        if text_data.strip(): # Add non-empty text
                            body_content_parts.append(f"<p>{text_data.strip()}</p>")
            if not body_content_parts: # If no text items were extracted, use a placeholder
                logger.warning(f"No text content found from TextBlocks for fallback in {title}. Using placeholder.")
                body_content_parts.append("<p>[Content could not be processed or was empty]</p>")

            fallback_body_content = "\n".join(body_content_parts)
            return self._wrap_body_fragments_in_full_xhtml(fallback_body_content, f"Fallback - {title}", lang)
        except Exception as e:
            logger.error(f"Error creating fallback XHTML for {title}: {e}", exc_info=True)
            # Super basic fallback if even text extraction fails
            return self._wrap_body_fragments_in_full_xhtml(
                "<p>[Error generating fallback content]</p>", f"Fallback Error - {title}", lang
            )

    def _create_text_chunks(self, texts: List[str], max_chars_per_chunk: int, join_separator="\n\n") -> List[str]:
        """
        Combines and splits a list of text strings into chunks, each not exceeding max_chars_per_chunk.
        Args:
            texts: A list of text strings.
            max_chars_per_chunk: The maximum character length for each chunk.
            join_separator: Separator used when joining multiple small texts into one chunk.
        Returns:
            A list of text chunks.
        """
        chunks: List[str] = []
        current_chunk_texts: List[str] = []
        current_chunk_chars = 0

        if max_chars_per_chunk <= 0: # No chunking by char length
            combined_text = join_separator.join(texts)
            if combined_text: chunks.append(combined_text)
            return chunks

        for text_item in texts:
            if not text_item.strip():
                continue

            if len(text_item) > max_chars_per_chunk:
                if current_chunk_texts: # Finalize current chunk
                    chunks.append(join_separator.join(current_chunk_texts))
                    current_chunk_texts = []
                    current_chunk_chars = 0
                for i in range(0, len(text_item), max_chars_per_chunk): # Split large item
                    chunks.append(text_item[i:i + max_chars_per_chunk])
            elif current_chunk_chars + len(text_item) + (len(join_separator) if current_chunk_texts else 0) > max_chars_per_chunk:
                chunks.append(join_separator.join(current_chunk_texts))
                current_chunk_texts = [text_item]
                current_chunk_chars = len(text_item)
            else:
                current_chunk_texts.append(text_item)
                current_chunk_chars += len(text_item) + (len(join_separator) if len(current_chunk_texts) > 1 else 0)
        
        if current_chunk_texts: # Add any remaining chunk
            chunks.append(join_separator.join(current_chunk_texts))
        return chunks

    def _process_single_segment_task_wrapper(self, task: SegmentProcessingTask) -> Tuple[Any, int, Optional[str], Optional[Exception]]:
        """
        Wrapper function to process a single XHTML segment.
        This is intended to be run in a ThreadPoolExecutor.
        Returns (xhtml_item_id, segment_index, generated_xhtml_str_or_None, error_or_None)
        """
        segment_id_prefix: str
        current_prompt_instructions: str
        is_fragment_request = task.total_segments_for_item > 1

        # Adapt the item's base prompt for fragment or full document processing
        if is_fragment_request:
            segment_id_prefix = f"{Path(task.xhtml_item_filename).stem}_part_{task.segment_index + 1}{Path(task.xhtml_item_filename).suffix}"
            
            base_universal_prompt = task.prompt_template_for_item.replace('{target_language}', task.target_language)
            prompt_cleaned_for_fragment = base_universal_prompt
            prompt_cleaned_for_fragment = re.sub(
                r"## 번역할 원문.*?({{#if content_items}}.*?{{/if}})",
                "## 번역할 원문\n(구조화된 콘텐츠 항목은 이 지침 다음에 별도의 JSON 형식으로 제공됩니다. 해당 항목들을 처리해주세요.)",
                prompt_cleaned_for_fragment, flags=re.DOTALL | re.IGNORECASE
            )
            if "{{lorebook_context}}" in prompt_cleaned_for_fragment:
                # For fragment mode, if we want to inject segment-specific lorebook,
                # we should NOT replace the placeholder here.
                # Instead, let the common injection logic below handle it using task.ebtg_lorebook_context_for_segment.
                # If the intention was to explicitly EXCLUDE lorebook for fragments, the original line was correct.
                # Assuming per-fragment lorebook is desired:
                pass # Keep {{lorebook_context}} placeholder for later injection
            

            fragment_directive = (
                "\n\nIMPORTANT INSTRUCTION FOR THIS SPECIFIC TASK (FRAGMENT MODE):\n"
                "You are currently processing a FRAGMENT of a larger document. "
                "Your output for THIS task must be ONLY the XHTML content for the body of this fragment. "
                "Do NOT include `<html>`, `<head>`, or `<body>` tags in your response. "
                "The content items for this fragment will be provided in a JSON block following all instructions."
            )
            current_prompt_instructions = prompt_cleaned_for_fragment + fragment_directive
        else:
            # This is for a single segment (entire document)
            # The prompt_template_for_item is already the full universal prompt.
            # We just need to replace {target_language} and {{lorebook_context}}.
            # {{lorebook_context}} will be replaced using task.ebtg_lorebook_context_for_segment.
            # {target_language} will be replaced from task.target_language.
            # So, task.prompt_template_for_item should be the raw universal template here.
            # The replacement of {target_language} and {{lorebook_context}} will happen next.

            segment_id_prefix = task.xhtml_item_filename
            current_prompt_instructions = task.prompt_template_for_item.replace(
                "{target_language}", task.target_language
            )

        logger.info(f"Requesting XHTML for {'fragment' if is_fragment_request else 'document'}: {segment_id_prefix} ({len(task.segment_items_data)} items)")
        
        # Inject EBTG-managed lorebook context (now using the pre-calculated one from the task)
        if "{{lorebook_context}}" in current_prompt_instructions:
            final_prompt_for_btg = current_prompt_instructions.replace("{{lorebook_context}}", task.ebtg_lorebook_context_for_segment)
            logger.info(f"EBTG: Injected pre-calculated lorebook context for {segment_id_prefix}. Context (first 100 chars): {task.ebtg_lorebook_context_for_segment[:100]}")
        else:
            final_prompt_for_btg = current_prompt_instructions
            logger.warning(f"EBTG: '{{{{lorebook_context}}}}' placeholder not found in prompt for {segment_id_prefix}, EBTG lorebook not injected.")
        try:
            generated_segment_xhtml_str = self.btg_integration.generate_xhtml(
                id_prefix=segment_id_prefix,
                content_items=task.segment_items_data,
                target_language=task.target_language,
                prompt_instructions=final_prompt_for_btg # Use the prompt with lorebook injected
            )

            if not generated_segment_xhtml_str:
                logger.error(f"BTG Integration returned no content for segment {segment_id_prefix}.")
                return task.xhtml_item_id, task.segment_index, None, ApiXhtmlGenerationError(f"No content from BTG for {segment_id_prefix}")

            actual_segment_content_to_use = generated_segment_xhtml_str
            if is_fragment_request:
                temp_soup_for_frag_check = BeautifulSoup(generated_segment_xhtml_str, 'html.parser')
                html_tag_in_frag = temp_soup_for_frag_check.find('html')
                body_tag_in_frag = temp_soup_for_frag_check.find('body')
                if html_tag_in_frag and body_tag_in_frag:
                    logger.debug(f"Segment {segment_id_prefix} (requested as fragment) appears to be a full document. Extracting body content.")
                    extracted_body_content = "".join(str(c) for c in body_tag_in_frag.contents).strip()
                    if extracted_body_content:
                        actual_segment_content_to_use = extracted_body_content
                    elif generated_segment_xhtml_str.strip():
                         logger.warning(f"Extracted empty body from full-doc fragment {segment_id_prefix}. Using original fragment string as fallback for this part.")
            
            is_valid_segment, validation_errors = self.quality_monitor.validate_xhtml_structure(
                actual_segment_content_to_use, segment_id_prefix
            )
            if not is_valid_segment:
                logger.error(f"XHTML segment content for {segment_id_prefix} is not well-formed. Errors: {validation_errors}.")
                # Return the malformed content along with an error for the main thread to decide on fallback for the whole item.
                return task.xhtml_item_id, task.segment_index, actual_segment_content_to_use, EbtgProcessingError(f"Segment {segment_id_prefix} not well-formed: {validation_errors}")

            logger.info(f"Successfully generated and validated XHTML segment content: {segment_id_prefix}.")
            return task.xhtml_item_id, task.segment_index, actual_segment_content_to_use, None

        except (ApiXhtmlGenerationError, BtgServiceException, EbtgProcessingError) as e_gen:
            logger.error(f"Error generating XHTML for segment {segment_id_prefix}: {e_gen}")
            return task.xhtml_item_id, task.segment_index, None, e_gen
        except Exception as e_unexpected_segment:
            logger.error(f"Unexpected error in segment processing {segment_id_prefix}: {e_unexpected_segment}", exc_info=True)
            return task.xhtml_item_id, task.segment_index, None, e_unexpected_segment

    def _translate_single_chunk_task_wrapper(
        self,
        chunk_text: str,
        chunk_idx: int, # For logging/error reporting
        target_language: str,
        prompt_template: str,
        lorebook_context: Optional[str]
    ) -> Tuple[int, str, Optional[Exception]]:
        """
        Wrapper to translate a single text chunk using BtgIntegrationService.
        Returns (chunk_idx, translated_fragment_or_error_placeholder, error_or_None)
        """
        try:
            # BtgIntegrationService로 전달될 기본 프롬프트 템플릿
            effective_prompt_template = prompt_template

            # Add instruction for handling merged chunks if separator is present
            if EBTG_MERGE_SEPARATOR in chunk_text:
                merge_handling_instruction = (
                    "\n\nIMPORTANT_CHUNK_PROCESSING_NOTE: The text provided in the '{{slot}}' for translation may contain "
                    f"multiple distinct pieces separated by the special marker '{EBTG_MERGE_SEPARATOR}'. "
                    "When you encounter this marker, you MUST translate each piece independently. "
                    "In your final XHTML fragment output, ensure that the translations of these pieces are also "
                    f"separated by the exact same marker string '{EBTG_MERGE_SEPARATOR}' "
                    "placed directly between their respective surrounding paragraph tags. "
                    "For example, if input for the slot is 'Text A<EBTG_TEXT_SEPARATOR_DO_NOT_TRANSLATE_THIS_TAG/>Text B', " # Simplified example for clarity
                    "your translated output for the slot (after your translation and wrapping) should be "
                    "'<p>[Translated Text A]</p><EBTG_TEXT_SEPARATOR_DO_NOT_TRANSLATE_THIS_TAG/><p>[Translated Text B]</p>'. "
                    "Preserve this separator meticulously in the output if it was in the input text for the slot."
                )
                # Add the instruction to the main prompt template.
                # This instruction is for the LLM about how to process the content of {{slot}}.
                effective_prompt_template += merge_handling_instruction

            # Approximate prompt character count for logging (before {{slot}} is filled by BTG's TranslationService)
            temp_prompt_for_char_count = effective_prompt_template.replace("{target_language}", target_language)
            if lorebook_context: # Ensure lorebook_context is not None before replacing
                temp_prompt_for_char_count = temp_prompt_for_char_count.replace("{{lorebook_context}}", lorebook_context)
            else:
                temp_prompt_for_char_count = temp_prompt_for_char_count.replace("{{lorebook_context}}", "") # Replace with empty if None
            
            prompt_char_count = len(temp_prompt_for_char_count) + len(chunk_text) # Add length of the chunk text itself
            logger.debug(f"Approx. prompt char count for API (chunk {chunk_idx}): {prompt_char_count} chars. Chunk text length: {len(chunk_text)}.")

            translated_fragment = self.btg_integration.translate_single_text_chunk_to_xhtml_fragment(
                text_chunk=chunk_text,
                target_language=target_language, # For BtgIntegrationService to fill {target_language}
                prompt_template_for_fragment_generation=effective_prompt_template, # Pass the (potentially modified) prompt
                ebtg_lorebook_context=lorebook_context # For BtgIntegrationService to fill {{lorebook_context}}
            )
            return chunk_idx, translated_fragment, None
        except Exception as e:
            logger.error(f"Error translating chunk {chunk_idx}: {e}", exc_info=True)
            return chunk_idx, f"<p>[Chunk {chunk_idx} Translation Error: {e}]</p>", e

    def get_all_text_from_epub(self, epub_path: str) -> str:
        """
        Extracts all textual content from the XHTML files within an EPUB.

        Args:
            epub_path: Path to the EPUB file.

        Returns:
            A single string containing all extracted text, joined by double newlines.
            Returns an empty string if no text is found or if XHTML items are missing.

        Raises:
            FileNotFoundError: If the EPUB file does not exist.
            EbtgProcessingError: For other critical errors during EPUB processing or text extraction.
        """
        logger.info(f"Attempting to extract all text from EPUB: {epub_path}")
        try:
            # Ensure the epub_processor is set for the correct book.
            # open_epub will clear previous state and load the new EPUB.
            self.epub_processor.open_epub(epub_path)
        except FileNotFoundError:
            logger.error(f"EPUB file not found for text extraction: {epub_path}")
            raise # Re-raise for the caller to handle
        except Exception as e:
            logger.error(f"Failed to open EPUB {epub_path} for text extraction: {e}", exc_info=True)
            raise EbtgProcessingError(f"Failed to open EPUB {epub_path}: {e}") from e

        xhtml_items: List[EpubXhtmlItem] = self.epub_processor.get_xhtml_items()

        if not xhtml_items:
            logger.warning(f"No XHTML items found in {epub_path}. Returning empty text.")
            return ""

        all_text_parts: List[str] = []
        for xhtml_item in xhtml_items:
            logger.debug(f"Extracting text from XHTML item: {xhtml_item.filename}")
            try:
                original_xhtml_content_str = xhtml_item.original_content_bytes.decode('utf-8', errors='replace')
                content_items = self.html_extractor.extract_content(original_xhtml_content_str)
                for element_obj in content_items: # Renamed item_dict to element_obj for clarity
                    if isinstance(element_obj, TextBlock):
                        if element_obj.text_content and element_obj.text_content.strip(): # Ensure non-empty, stripped text
                            all_text_parts.append(element_obj.text_content.strip())
                    # If ImageInfo alt text also needs to be extracted here, add:
                    # elif isinstance(element_obj, ImageInfo) and element_obj.original_alt and element_obj.original_alt.strip():
                    #     all_text_parts.append(element_obj.original_alt.strip())
            
            except UnicodeDecodeError as ude:
                logger.warning(f"Unicode decode error for {xhtml_item.filename}: {ude}. Skipping text from this item.")
            except XhtmlExtractionError as xee:
                logger.warning(f"XHTML extraction error for {xhtml_item.filename}: {xee}. Skipping text from this item.")
            except Exception as e_item:
                logger.error(f"Unexpected error processing text from {xhtml_item.filename}: {e_item}", exc_info=True)
        
        if not all_text_parts:
            logger.info(f"No textual content was extracted from any XHTML file in {epub_path}.")
            return ""

        full_text = "\n\n".join(all_text_parts)
        logger.info(f"Successfully extracted approximately {len(full_text)} characters of text from {epub_path}.")
        return full_text

    def translate_epub(
        self,
        input_epub_path: str,
        output_epub_path: str,
        progress_callback: Optional[Callable[[EpubProcessingProgressDTO], None]] = None
    ) -> None:
        """
        Processes an EPUB file: extracts XHTML content, sends it for translation
        (XHTML generation) via BTG module, and reassembles the EPUB.
        Args:
            input_epub_path: Path to the input EPUB file.
            output_epub_path: Path to save the translated EPUB file.
            progress_callback: Optional callback function to report progress.
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
            
            # Store original items for easy access by item_id
            original_items_map: Dict[Any, EpubXhtmlItem] = {item.item_id: item for item in xhtml_items}

            if progress_callback:
                progress_callback(EpubProcessingProgressDTO(
                    total_files=total_files, processed_files=0,
                    current_file_name=None,
                    errors_count=files_with_errors,
                    status_message="EPUB 처리 시작..."
                ))

            logger.info(f"Found {total_files} XHTML files to process.")
            target_language = self.config.get("target_language", "ko")
            # This is the base prompt template for an entire XHTML item.
            # It will be adapted by _process_single_segment_task_wrapper if an item is split into fragments.
            universal_prompt_template = self.config.get(
                    "universal_translation_prompt" 
                    # Default prompt string removed for brevity, EbtgConfigManager provides it
            )
            if not universal_prompt_template: # Should be provided by EbtgConfigManager
                raise EbtgProcessingError("Universal translation prompt is not configured.")

            # Unified segment character limit
            segment_char_limit = self.config.get("segment_character_limit", 4000)


            for xhtml_item in xhtml_items:
                processed_files += 1
                item_filename = xhtml_item.filename
                item_id = xhtml_item.item_id
                original_xhtml_content_str: str = ""
                generated_xhtml_for_item_successfully = False

                logger.info(f"Processing file {processed_files}/{total_files}: {item_filename}")
                if progress_callback:
                    progress_callback(EpubProcessingProgressDTO(
                        total_files=total_files,
                        processed_files=processed_files -1, # Current file is being processed
                        current_file_name=item_filename,
                        errors_count=files_with_errors,
                        status_message=f"파일 처리 중: {item_filename}"
                    ))


                try:
                    original_xhtml_content_str = xhtml_item.original_content_bytes.decode('utf-8', errors='replace')
                    
                    # Phase 2: Extract ExtractedContentElement list
                    extracted_elements: List[ExtractedContentElement] = self.html_extractor.extract_content(original_xhtml_content_str)

                    if not extracted_elements:
                        logger.warning(f"No content elements extracted from {item_filename} by SimplifiedHtmlExtractor. Keeping original content.")
                        self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "skipped_empty_content")
                        continue

                    # --- Start: Phase 3 - Text Extraction, Chunking, and BTG Request Preparation ---
                    # The old segmentation logic (ContentSegmentationService, SegmentProcessingTask, _process_single_segment_task_wrapper)
                    # was for the previous architecture where EBTG sent structured items to BTG for full XHTML generation.
                    # This is now replaced by extracting plain text, chunking it, and sending it for fragment translation.

                    logger.info(f"[{item_filename}] Starting Phase 3: Text extraction and preparation for BTG.")
                    
                    texts_for_translation_for_item: List[str] = []
                    alt_text_details_map: Dict[str, Tuple[ImageInfo, str]] = {} # Value: (ImageInfo_object, original_alt_text)
                    alt_text_id_counter = 0 # Reset for each item

                    for element_idx, element_obj in enumerate(extracted_elements):
                        if isinstance(element_obj, TextBlock):
                            if element_obj.text_content.strip():
                                texts_for_translation_for_item.append(element_obj.text_content)
                        elif isinstance(element_obj, ImageInfo):
                            # ImageInfo object itself is preserved in extracted_elements.
                            # If it has alt text, add that to the list for translation.
                            if element_obj.original_alt and element_obj.original_alt.strip():
                                # Create a unique ID for this alt text to map it back after translation.
                                unique_alt_id = f"{Path(item_filename).stem}_alt_{alt_text_id_counter}"
                                # Store the ImageInfo object and its original alt text for later reassembly
                                alt_text_details_map[unique_alt_id] = (element_obj, element_obj.original_alt)
                                alt_text_id_counter += 1
                                texts_for_translation_for_item.append(element_obj.original_alt) # Add alt text to translation list

                    logger.info(f"For {item_filename}: Extracted {len(texts_for_translation_for_item)} text/alt-text strings for translation.")
                    logger.debug(f"For {item_filename}: texts_for_translation_for_item (first 3): {texts_for_translation_for_item[:3]}")
                    logger.debug(f"For {item_filename}: alt_text_details_map (first 3 items): {list(alt_text_details_map.items())[:3]}")

                    if not texts_for_translation_for_item:
                        logger.info(f"[{item_filename}] No text or alt-text found for translation. Keeping original content.")
                        self.epub_processor.update_xhtml_content(item_id, original_xhtml_content_str.encode('utf-8'))
                        self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "kept_original_no_translatable_text")
                        generated_xhtml_for_item_successfully = True # Considered "successful"
                        continue
                        
                    # --- NEW: Merge texts in texts_for_translation_for_item ---
                    merged_texts_for_btg: List[str] = []
                    # source_map_for_merged_texts maps index in merged_texts_for_btg
                    # to a list of original indices from texts_for_translation_for_item
                    source_map_for_merged_texts: List[List[int]] = []

                    current_merged_parts_texts: List[str] = []
                    current_merged_parts_original_indices: List[int] = []
                    current_merged_char_count = 0

                    for original_idx, original_text_content in enumerate(texts_for_translation_for_item):
                        if not original_text_content.strip(): # Skip empty original texts
                            continue

                        # If current_merged_parts_texts is not empty and adding the new text (plus separator)
                        # would exceed the limit, finalize the current merged chunk.
                        if current_merged_parts_texts and \
                           (current_merged_char_count + len(EBTG_MERGE_SEPARATOR) + len(original_text_content) > segment_char_limit):
                            merged_texts_for_btg.append(EBTG_MERGE_SEPARATOR.join(current_merged_parts_texts))
                            source_map_for_merged_texts.append(list(current_merged_parts_original_indices))
                            current_merged_parts_texts = []
                            current_merged_parts_original_indices = []
                            current_merged_char_count = 0

                        # If a single original_text_content itself is larger than segment_char_limit,
                        # it forms its own "merged" chunk (or could be further split if needed, but current logic sends as is).
                        if not current_merged_parts_texts and len(original_text_content) > segment_char_limit:
                            merged_texts_for_btg.append(original_text_content)
                            source_map_for_merged_texts.append([original_idx])
                            # No change to current_merged_parts_texts etc., as this one is processed immediately.
                        else:
                            current_merged_parts_texts.append(original_text_content)
                            current_merged_parts_original_indices.append(original_idx)
                            current_merged_char_count += len(original_text_content)
                            if len(current_merged_parts_texts) > 1:
                                current_merged_char_count += len(EBTG_MERGE_SEPARATOR)

                    if current_merged_parts_texts: # Add any remaining parts
                        merged_texts_for_btg.append(EBTG_MERGE_SEPARATOR.join(current_merged_parts_texts))
                        source_map_for_merged_texts.append(list(current_merged_parts_original_indices))
                    
                    text_chunks_for_btg = merged_texts_for_btg # Use the merged chunks
                    logger.info(f"[{item_filename}] Created {len(text_chunks_for_btg)} merged text chunks for BTG from {len(texts_for_translation_for_item)} original text items.")

                    
                    if not text_chunks_for_btg: # Should not happen if texts_for_translation_for_item was not empty
                        logger.warning(f"[{item_filename}] Text chunking resulted in zero chunks. Keeping original content.")
                        self.epub_processor.update_xhtml_content(item_id, original_xhtml_content_str.encode('utf-8'))
                        self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "kept_original_empty_chunks")
                        generated_xhtml_for_item_successfully = True
                        continue

                    # Prepare prompt and lorebook context
                    # The prompt template from config will have {target_language}, {ebtg_lorebook_context}, and {{slot}}
                    # Use the universal_translation_prompt, its {{else}} block is now designed for fragment generation.
                    prompt_template_for_fragments = self.config.get("universal_translation_prompt")
                    if not prompt_template_for_fragments: # Fallback if key is missing for some reason
                        raise EbtgProcessingError("Universal translation prompt is not configured in EBTG settings.")
                    ebtg_lorebook_context_for_item = self._get_relevant_lorebook_context_for_extracted_elements(extracted_elements)

                    

                    logger.info(f"[{item_filename}] Sending {len(text_chunks_for_btg)} text chunks to BtgIntegrationService for translation and fragment generation.")
                    
                    # Call BtgIntegrationService (This method needs to be implemented in BtgIntegrationService)
                    # It's expected to use BtgAppService to call the LLM for each chunk.
                    try:
                        # --- Parallelized Text Chunk Translation ---
                        max_workers_for_ebtg = self.config.get("max_workers", 4) # Use the same max_workers as for BTG
                        # translated_fragments_map maps index in text_chunks_for_btg (merged_texts_for_btg) to translated fragment
                        translated_merged_fragments_map: Dict[int, str] = {}
                        chunk_translation_errors: List[str] = []

                        with ThreadPoolExecutor(max_workers=max_workers_for_ebtg) as executor:
                            future_to_chunk_idx: Dict[Any, int] = {}
                            for idx, chunk_to_translate in enumerate(text_chunks_for_btg):
                                future = executor.submit(
                                    self._translate_single_chunk_task_wrapper,
                                    chunk_text=chunk_to_translate,
                                    chunk_idx=idx,
                                    target_language=target_language,
                                    prompt_template=prompt_template_for_fragments,
                                    lorebook_context=ebtg_lorebook_context_for_item
                                )
                                future_to_chunk_idx[future] = idx

                            for future in as_completed(future_to_chunk_idx):
                                original_chunk_idx = future_to_chunk_idx[future]
                                try:
                                    _c_idx, translated_merged_frag, error = future.result()
                                    translated_merged_fragments_map[original_chunk_idx] = translated_merged_frag
                                    if error:
                                        chunk_translation_errors.append(f"Chunk {original_chunk_idx}: {error}")
                                except Exception as exc:
                                    logger.error(f"Error processing future for chunk {original_chunk_idx}: {exc}")
                                    translated_merged_fragments_map[original_chunk_idx] = f"<p>[Merged Chunk {original_chunk_idx} Processing Error: {exc}]</p>"
                                    chunk_translation_errors.append(f"Chunk {original_chunk_idx} (Future): {exc}")
                        
                        if chunk_translation_errors:
                            logger.error(f"[{item_filename}] Errors encountered during parallel text chunk translation. Errors: {chunk_translation_errors}. Using fallback.")
                            raise EbtgProcessingError(f"Failed to translate one or more text chunks for {item_filename}.")

                        # --- Deconstruct merged fragments and map to original texts ---
                        final_individual_translations: Dict[int, str] = {} # Maps original_idx from texts_for_translation_for_item to its translated fragment

                        for merged_idx, translated_merged_fragment in translated_merged_fragments_map.items():
                            original_indices_for_this_merged_chunk = source_map_for_merged_texts[merged_idx]
                            
                            # Split the translated_merged_fragment by EBTG_MERGE_SEPARATOR
                            # The LLM was instructed to preserve this separator.
                            individual_translated_parts = translated_merged_fragment.split(EBTG_MERGE_SEPARATOR)

                            if len(individual_translated_parts) == len(original_indices_for_this_merged_chunk):
                                for i, original_text_idx in enumerate(original_indices_for_this_merged_chunk):
                                    final_individual_translations[original_text_idx] = individual_translated_parts[i].strip()
                            else:
                                logger.warning(f"[{item_filename}] Mismatch after splitting translated merged chunk {merged_idx}. Expected {len(original_indices_for_this_merged_chunk)} parts, got {len(individual_translated_parts)}. Fallback for these parts.")
                                for original_text_idx in original_indices_for_this_merged_chunk:
                                    final_individual_translations[original_text_idx] = f"<p>[Translation Error - Mismatch in merged chunk {merged_idx}]</p>"
                        # --- End Parallelized Text Chunk Translation ---
                                                
                        # Now, use `reconstructed_original_item_translations` for reassembly with `extracted_elements`.
                        reassembled_xhtml_parts = [] # Reset for correct reassembly

                        current_original_text_idx = 0 # To iterate through final_individual_translations
                        for element in extracted_elements:
                            if isinstance(element, TextBlock):
                                if element.text_content.strip():
                                    try:
                                        translated_fragment = final_individual_translations.get(current_original_text_idx, f"<p>[Missing Translation for original_text_idx {current_original_text_idx}]</p>")
                                        reassembled_xhtml_parts.append(translated_fragment)
                                        current_original_text_idx += 1
                                    except KeyError: # Should be caught by .get() default
                                        logger.error(f"[{item_filename}] Reassembly error: Missing translation for original_text_idx {current_original_text_idx}.")
                                        reassembled_xhtml_parts.append(f"<p>[Translation Error for TextBlock]</p>")
                                        files_with_errors += 1
                                elif not element.text_content.strip(): # Empty text block
                                    reassembled_xhtml_parts.append("<p></p>") # Or however empty paragraphs should be represented

                            elif isinstance(element, ImageInfo):
                                translated_alt_text = element.original_alt # Default to original if not translated
                                if element.original_alt and element.original_alt.strip():
                                    try:
                                        translated_alt_fragment = final_individual_translations.get(current_original_text_idx, element.original_alt)
                                        
                                        soup_alt = BeautifulSoup(translated_alt_fragment, 'html.parser')
                                        translated_alt_text = soup_alt.get_text().strip()
                                        current_original_text_idx += 1
                                    except StopIteration:
                                        logger.error(f"[{item_filename}] Reassembly (v2) error: Ran out of translated alt text fragments.")
                                    except Exception as e_alt_parse:
                                        logger.warning(f"Failed to parse alt text fragment for reassembly (v2): {e_alt_parse}.")
                                
                                final_alt_text_for_tag = translated_alt_text if translated_alt_text else ""
                                # Preserve original img tag structure, only update alt
                                temp_img_soup = BeautifulSoup(element.original_tag_string, 'html.parser')
                                img_tag_obj = temp_img_soup.find('img')
                                if img_tag_obj: # type: ignore
                                    img_tag_obj['alt'] = final_alt_text_for_tag # type: ignore
                                    reassembled_xhtml_parts.append(str(img_tag_obj))
                                else: # Fallback if original_tag_string was not a valid img tag
                                    reassembled_xhtml_parts.append(f'<img src="{element.src}" alt="{final_alt_text_for_tag}"/>')
                        
                        final_xhtml_content_str = "\n".join(reassembled_xhtml_parts)
                        # --- End: Phase 5 ---

                        # Validate and update EPUB content
                        is_valid_xhtml, validation_errors = self.quality_monitor.validate_xhtml_structure(final_xhtml_content_str, item_filename)
                        if not is_valid_xhtml:
                            logger.error(f"[{item_filename}] Reassembled XHTML is not well-formed: {validation_errors}. Using fallback.")
                            raise EbtgProcessingError(f"Reassembled XHTML for {item_filename} failed validation.")

                        self.epub_processor.update_xhtml_content(item_id, final_xhtml_content_str.encode('utf-8'))
                        self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, "translated_reassembled_successfully")
                        generated_xhtml_for_item_successfully = True
                        logger.info(f"[{item_filename}] Successfully reassembled and updated in EPUB.")
                        # --- End: Phase 5 ---

                    except (BtgServiceException, EbtgProcessingError) as e_btg_reassembly:
                        logger.error(f"[{item_filename}] Error during BTG call or reassembly: {e_btg_reassembly}. Using fallback.")
                        fallback_xhtml = self._create_fallback_xhtml(original_xhtml_content_str, Path(item_filename).stem, target_language)
                        self.epub_processor.update_xhtml_content(item_id, fallback_xhtml.encode('utf-8'))
                        self.progress_service.record_xhtml_status(Path(input_epub_path).name, item_filename, f"failed_reassembly_fallback", str(e_btg_reassembly))
                        files_with_errors += 1

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
            
            if progress_callback:
                progress_callback(EpubProcessingProgressDTO(
                    total_files=total_files,
                    processed_files=processed_files,
                    current_file_name=None,
                    errors_count=files_with_errors,
                    status_message="EPUB 처리 완료, 저장 중..."
                ))

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

            if progress_callback:
                progress_callback(EpubProcessingProgressDTO(
                    total_files=total_files,
                    processed_files=processed_files,
                    current_file_name=None,
                    errors_count=files_with_errors,
                    status_message="EPUB 번역 완료!"
                ))

        except FileNotFoundError as e:
            logger.error(f"Input EPUB file not found: {input_epub_path} - {e}")
            if progress_callback:
                progress_callback(EpubProcessingProgressDTO(total_files=0, processed_files=0, errors_count=1, status_message=f"오류: 입력 파일을 찾을 수 없습니다 - {Path(input_epub_path).name}"))
            raise EbtgProcessingError(f"Input EPUB not found: {input_epub_path}") from e
        except Exception as e:
            logger.error(f"An error occurred during EPUB translation: {e}", exc_info=True)
            self.progress_service.save_progress(output_epub_path) # Attempt to save progress even if main process fails
            if progress_callback: # Corrected indent for this block
                progress_callback(EpubProcessingProgressDTO(
                    total_files=total_files if 'total_files' in locals() else 0, 
                    processed_files=processed_files if 'processed_files' in locals() else 0, 
                    errors_count=files_with_errors + 1 if 'files_with_errors' in locals() else 1, 
                    status_message=f"EPUB 번역 중 심각한 오류: {e}"
                ))
            raise EbtgProcessingError(f"EPUB translation failed: {e}") from e # Corrected indent for this line