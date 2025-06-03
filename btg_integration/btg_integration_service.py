# ebtg/btg_integration_service.py
import logging
from typing import List, Dict, Any, Optional

from btg_module.app_service import AppService as BtgAppService
from btg_module.dtos import XhtmlGenerationRequestDTO, XhtmlGenerationResponseDTO
from btg_module.exceptions import BtgServiceException, BtgApiClientException

from ebtg.ebtg_exceptions import ApiXhtmlGenerationError, EbtgProcessingError
from ebtg.ebtg_dtos import TranslateTextChunksRequestDto, TranslateTextChunksResponseDto

logger = logging.getLogger(__name__)

class BtgIntegrationService:
    def __init__(self, btg_app_service: BtgAppService, ebtg_config: Dict[str, Any]):
        self.btg_app_service = btg_app_service
        self.ebtg_config = ebtg_config
        logger.info("BtgIntegrationService initialized.")

    def generate_xhtml(
        self, 
        id_prefix: str, 
        content_items: List[Dict[str, Any]], 
        target_language: str,
        prompt_instructions: str
    ) -> Optional[str]:
        logger.info(f"Requesting XHTML generation from BTG for id_prefix: {id_prefix}")

        response_schema_for_gemini = {
            "type": "OBJECT",
            "properties": {"translated_xhtml_content": {"type": "STRING"}},
        }
        
        # --- Prompt Enhancements (Phase 2) ---
        # prompt_instructions is the base instruction from EBTG (derived from universal_translation_prompt)
        ebtg_provided_base_instructions = prompt_instructions
        # 1. <img> 위치 보존 강화 프롬프트
        img_pos_instruction = (
            "Image Placement: Images (represented by {'type': 'image', ...} items in the "
            "'content_items' list) are critical. They MUST be placed precisely between the "
            "text blocks where they originally appeared. The 'content_items' list preserves "
            "this original sequence. If 'context_before_snippet' and 'context_after_snippet' "
            "fields are present in an image's data, use them as strong hints for accurate "
            "placement relative to the surrounding text."
        )

        # 2. 기본 블록 구조 유지 프롬프트
        block_structure_instruction = (
            "Basic Block Structure: Ensure consistent use of fundamental HTML block-level tags. "
            "Primarily, use <p> tags for all paragraphs of text. If the text content clearly "
            "suggests headings (e.g., chapter titles, section headers), use appropriate <h1> to <h6> tags. "
            "If list structures (ordered or unordered) can be reliably inferred from the text, "
            "use <ul><li>...</li></ul> or <ol><li>...</li></ol> tags accordingly."
        )

        # 3. (선택적) 소설의 일반적인 스타일 (대화)
        novel_style_instruction = (
            "Novel Dialogue Formatting: For dialogue sections, if they can be identified "
            "(e.g., lines starting with quotation marks, em-dashes, or other common dialogue indicators), "
            "please ensure each distinct spoken line or piece of dialogue is enclosed in its own <p> tag. "
            "Maintain the original flow and separation of dialogue from narrative text."
        )

        # --- Phase 3: Advanced Prompt Engineering ---
        # 1. 소설 특화 프롬프트 (대화문, 지문, 특정 문체 등)
        novel_specific_prompt_details = (
            "Novel-Specific Formatting Details:\n"
            "- Dialogue Handling: As previously mentioned, ensure each spoken line is in its own <p> tag. "
            "If speaker attributions (e.g., 'he said', 'Alice whispered') are present, integrate them naturally "
            "with the dialogue, typically within the same paragraph or an immediately adjacent one if it reflects the narrative structure.\n"
            "  Example Input: {\"type\": \"text\", \"data\": \"\\\"Stop!\\\" he cried.\"}\n"
            "  Desired XHTML: <p>“Stop!” he cried.</p>\n"
            "- Narration and Description: All narrative blocks, character thoughts, and descriptive passages must also be wrapped in <p> tags. "
            "Maintain clear distinctions between dialogue and narration. Paragraph breaks implied by the sequence of 'content_items' "
            "often signify shifts in time, scene, or focus and should be respected with new <p> tags.\n"
            "- Literary Styles: While direct style tag generation (e.g., <i>, <b>) is not the primary goal, if the input text "
            "implies emphasis, thoughts (often italicized), or sound effects (often bolded), the translated text should convey this intent. "
            "The LLM should focus on semantic representation rather than literal tag reproduction unless explicitly part of a more advanced schema (not used here)."
        )

        # 2. "Few-shot" 프롬프팅 실험 (플레이스홀더 및 설명)
        few_shot_examples_placeholder_instruction = (
            "Illustrative Few-Shot Examples (Guidance for LLM - Actual examples would be injected here if used):\n"
            "To further clarify the desired output structure, consider these hypothetical examples:\n"
            "Example 1 (Text Only):\n"
            "  Input Content Item: {\"type\": \"text\", \"data\": \"The old house stood on a hill.\"}\n"
            "  Expected XHTML Output Fragment: <p>The old house stood on a hill.</p>\n"
            "Example 2 (Text and Image):\n"
            "  Input Content Items: [{\"type\": \"text\", \"data\": \"A path led to the door.\"}, {\"type\": \"image\", \"data\": {\"src\": \"door.jpg\", \"alt\": \"An old wooden door\"}}]\n"
            "  Expected XHTML Output Fragment: <p>A path led to the door.</p><img src=\"door.jpg\" alt=\"An old wooden door\"/>\n"
            "(End of illustrative few-shot example section. The actual 'content_items' follow the main instructions.)"
        )
        # --- End Phase 3 ---

        enhanced_prompt_instructions = (
            f"{ebtg_provided_base_instructions}\n\n" # EBTG에서 온 프롬프트를 가장 먼저 배치
            f"Regardless of the above, strictly adhere to the following technical instructions for XHTML generation:\n" # 명확한 구분
            f"{img_pos_instruction}\n\n" # 기술적 지시사항 시작
            f"{block_structure_instruction}\n\n"
            f"{novel_style_instruction}\n\n" # This is the general novel style from Phase 2
            f"{novel_specific_prompt_details}\n\n" # More detailed novel-specifics from Phase 3
            f"{few_shot_examples_placeholder_instruction}" # Few-shot placeholder from Phase 3
        )
        

        request_dto = XhtmlGenerationRequestDTO(
            id_prefix=id_prefix,
            content_items=content_items,
            target_language=target_language,
            prompt_instructions=enhanced_prompt_instructions, # Use the enhanced prompt
            response_schema_for_gemini=response_schema_for_gemini
        )

        try:
            if not self.btg_app_service.translation_service:
                 logger.error("BTG TranslationService is not initialized. Cannot generate XHTML.")
                 raise ApiXhtmlGenerationError("BTG module's TranslationService not ready.")

            logger.debug(f"Sending XhtmlGenerationRequestDTO to BTG: id_prefix={id_prefix}, {len(content_items)} items.")
            response_dto: XhtmlGenerationResponseDTO = self.btg_app_service.generate_xhtml_from_content_items(request_dto)

            if not isinstance(response_dto, XhtmlGenerationResponseDTO):
                logger.error(f"BTG AppService returned an unexpected type: {type(response_dto)}. Expected XhtmlGenerationResponseDTO.")
                raise ApiXhtmlGenerationError(f"BTG AppService returned an unexpected type: {type(response_dto)}")

            if response_dto.error_message:
                logger.error(f"BTG reported error for {id_prefix}: {response_dto.error_message}")
                return None 
            
            if response_dto.generated_xhtml_string:
                logger.info(f"Successfully received generated XHTML from BTG for {id_prefix}.")
                return response_dto.generated_xhtml_string
            else:
                logger.warning(f"BTG returned no XHTML string and no error for {id_prefix}. Assuming failure.")
                return None

        except ApiXhtmlGenerationError: # If ApiXhtmlGenerationError is raised directly (e.g., by mock or initial check)
            raise # Re-raise it so test assertions can catch it
        except (BtgApiClientException, BtgServiceException) as e: 
            logger.error(f"BTG Exception for {id_prefix}: {e}", exc_info=True)
            raise ApiXhtmlGenerationError(f"Error via BTG for {id_prefix}: {e}") from e
        except Exception as e:
            # This block will now only catch exceptions other than ApiXhtmlGenerationError,
            # BtgApiClientException, or BtgServiceException that might occur.
            logger.error(f"Unexpected error in BtgIntegrationService for {id_prefix}: {e}", exc_info=True)
            # Consider if this should also raise ApiXhtmlGenerationError or return None
            return None

    def translate_single_text_chunk_to_xhtml_fragment(
        self,
        text_chunk: str,
        target_language: str,
        prompt_template_for_fragment_generation: str, # Should have {{slot}}
        ebtg_lorebook_context: Optional[str]
    ) -> str:
        """
        Translates a single text chunk into an XHTML fragment using the BTG module.
        This is a helper method for EbtgAppService to use with ThreadPoolExecutor.
        """
        logger.debug(f"BtgIntegrationService: Translating single chunk. Lang: {target_language}, Chunk (start): {text_chunk[:50]}...")

        if not self.btg_app_service.translation_service:
            logger.error("BTG TranslationService is not initialized. Cannot translate single text chunk.")
            raise EbtgProcessingError("BTG module's TranslationService not ready for single chunk translation.")

        # Prepare the prompt by filling in language and lorebook context
        # The {{slot}} will be filled by BTG's TranslationService.
        prompt_with_context = prompt_template_for_fragment_generation.replace(
            "{target_language}", target_language
        ).replace(
            "{ebtg_lorebook_context}", ebtg_lorebook_context or "제공된 로어북 컨텍스트 없음"
        )

        try:
            fragment: str = self.btg_app_service.translation_service.translate_text_to_xhtml_fragment(
                text_chunk=text_chunk,
                target_language=target_language,
                prompt_template_with_context_and_slot=prompt_with_context # This prompt still has {{slot}}
            )
            logger.debug(f"Successfully translated single chunk to fragment: '{fragment[:100]}...'")
            return fragment
        except (BtgApiClientException, BtgServiceException) as e:
            logger.error(f"Error translating single text chunk to XHTML fragment: {e}", exc_info=True)
            raise # Re-raise to be caught by the calling ThreadPoolExecutor future
        except Exception as e_unexpected:
            logger.error(f"Unexpected error translating single text chunk: {e_unexpected}", exc_info=True)
            # Consider if this should also raise ApiXhtmlGenerationError or return None
            return None

    def translate_text_chunks(
        self,
        request_dto: TranslateTextChunksRequestDto
    ) -> TranslateTextChunksResponseDto:
        """
        Orchestrates the translation of text chunks into XHTML fragments by calling the BTG module.

        Args:
            request_dto: Contains text chunks, target language, prompt template, and lorebook context.

        Returns:
            A DTO containing the list of translated XHTML fragments and any errors.
        """
        logger.info(f"BtgIntegrationService: Received request to translate {len(request_dto.text_chunks)} text chunks to XHTML fragments for language '{request_dto.target_language}'.")

        translated_fragments: List[str] = []
        errors_list: List[Dict[str, Any]] = []

        if not self.btg_app_service.translation_service:
            logger.error("BTG TranslationService is not initialized. Cannot translate text chunks.")
            # This is a critical setup error.
            raise EbtgProcessingError("BTG module's TranslationService not ready for chunk translation.")

        # Prepare the base prompt by filling in language and lorebook context once
        # The {{slot}} will be filled by the BTG module for each chunk.
        prompt_template_with_context = request_dto.prompt_template_for_fragment_generation.replace(
            "{target_language}", request_dto.target_language
        ).replace(
            "{ebtg_lorebook_context}", request_dto.ebtg_lorebook_context or "제공된 로어북 컨텍스트 없음"
        )

        for index, text_chunk in enumerate(request_dto.text_chunks):
            try:
                logger.debug(f"Translating chunk {index + 1}/{len(request_dto.text_chunks)} to XHTML fragment.")
                # This method `translate_text_to_xhtml_fragment` is expected to be implemented in BTG's TranslationService (Phase 4)
                # It will take the prompt_template_with_context (which includes the {{slot}} placeholder),
                # replace {{slot}} with text_chunk, call Gemini with the appropriate schema, and return the fragment string.
                fragment: str = self.btg_app_service.translation_service.translate_text_to_xhtml_fragment(
                    text_chunk=text_chunk,
                    target_language=request_dto.target_language, # Passed for consistency, though already in prompt
                    prompt_template_with_context_and_slot=prompt_template_with_context # This prompt still has {{slot}}
                )
                translated_fragments.append(fragment)
                logger.debug(f"Successfully translated chunk {index + 1} to fragment: '{fragment[:100]}...'")

            except (BtgApiClientException, BtgServiceException) as e:
                logger.error(f"Error translating text chunk {index} to XHTML fragment: {e}", exc_info=True)
                errors_list.append({"chunk_index": index, "original_chunk_preview": text_chunk[:100], "error_message": str(e)})
            except Exception as e_unexpected:
                logger.error(f"Unexpected error translating text chunk {index} to XHTML fragment: {e_unexpected}", exc_info=True)
                errors_list.append({"chunk_index": index, "original_chunk_preview": text_chunk[:100], "error_message": f"Unexpected error: {str(e_unexpected)}"})

        logger.info(f"Finished translating text chunks. Got {len(translated_fragments)} fragments, encountered {len(errors_list)} errors.")
        return TranslateTextChunksResponseDto(translated_xhtml_fragments=translated_fragments, errors=errors_list if errors_list else None)