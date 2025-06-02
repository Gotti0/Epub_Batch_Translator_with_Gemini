# ebtg/btg_integration_service.py
import logging
from typing import List, Dict, Any, Optional

from btg_module.app_service import AppService as BtgAppService
from btg_module.dtos import XhtmlGenerationRequestDTO, XhtmlGenerationResponseDTO
from btg_module.exceptions import BtgServiceException, BtgApiClientException

from ..ebtg.ebtg_exceptions import ApiXhtmlGenerationError 

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
        
        request_dto = XhtmlGenerationRequestDTO(
            id_prefix=id_prefix,
            content_items=content_items,
            target_language=target_language,
            prompt_instructions=prompt_instructions,
            response_schema_for_gemini=response_schema_for_gemini
        )

        try:
            if not self.btg_app_service.translation_service:
                 logger.error("BTG TranslationService is not initialized. Cannot generate XHTML.")
                 raise ApiXhtmlGenerationError("BTG module's TranslationService not ready.")

            logger.debug(f"Sending XhtmlGenerationRequestDTO to BTG: id_prefix={id_prefix}, {len(content_items)} items.")
            response_dto: XhtmlGenerationResponseDTO = self.btg_app_service.generate_xhtml_from_content_items(request_dto)

            if response_dto.error_message:
                logger.error(f"BTG reported error for {id_prefix}: {response_dto.error_message}")
                return None 
            
            if response_dto.generated_xhtml_string:
                logger.info(f"Successfully received generated XHTML from BTG for {id_prefix}.")
                return response_dto.generated_xhtml_string
            else:
                logger.warning(f"BTG returned no XHTML string and no error for {id_prefix}. Assuming failure.")
                return None

        except (BtgApiClientException, BtgServiceException) as e: 
            logger.error(f"BTG Exception for {id_prefix}: {e}", exc_info=True)
            raise ApiXhtmlGenerationError(f"Error via BTG for {id_prefix}: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error in BtgIntegrationService for {id_prefix}: {e}", exc_info=True)
            return None