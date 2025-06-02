# ebtg/btg_integration_service.py
import logging
from typing import List, Dict, Any, Optional

from btg_module.app_service import AppService as BtgAppService
from btg_module.dtos import XhtmlGenerationRequestDTO, XhtmlGenerationResponseDTO
from btg_module.exceptions import BtgServiceException, BtgApiClientException

from ebtg.ebtg_exceptions import ApiXhtmlGenerationError 

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
        base_prompt_instructions = prompt_instructions # From ebtg_config

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
            f"{base_prompt_instructions}\n\n"
            f"{img_pos_instruction}\n\n"
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