# ebtg/tests/test_btg_integration_service.py
import unittest
from unittest.mock import MagicMock, patch
from btg_integration.btg_integration_service import BtgIntegrationService
from btg_module.dtos import XhtmlGenerationRequestDTO, XhtmlGenerationResponseDTO
from ebtg.ebtg_exceptions import ApiXhtmlGenerationError

class TestBtgIntegrationService(unittest.TestCase):

    def setUp(self):
        self.mock_btg_app_service = MagicMock()
        # Ensure translation_service attribute exists on the mock
        self.mock_btg_app_service.translation_service = MagicMock() 

        self.ebtg_config = {
            "target_language": "ko", # Default, can be overridden in tests
            "prompt_instructions_for_xhtml_generation": "Test Prompt Instructions: {{content_items}} Target: {{target_language}}"
        }
        self.integration_service = BtgIntegrationService(
            btg_app_service=self.mock_btg_app_service,
            ebtg_config=self.ebtg_config
        )

    def test_generate_xhtml_success(self):
        test_id_prefix = "test_doc"
        test_content_items = [{"type": "text", "data": "Hello"}]
        test_target_lang = "fr"
        test_prompt_instr = "Translate this to French: {{content_items}}"

        expected_xhtml_output = "<html><body><p>Bonjour</p></body></html>"

        self.mock_btg_app_service.generate_xhtml_from_content_items.return_value = XhtmlGenerationResponseDTO(
            id_prefix=test_id_prefix,
            generated_xhtml_string=expected_xhtml_output
        )

        result_xhtml = self.integration_service.generate_xhtml(
            id_prefix=test_id_prefix,
            content_items=test_content_items,
            target_language=test_target_lang,
            prompt_instructions=test_prompt_instr
        )

        self.assertEqual(result_xhtml, expected_xhtml_output)

        # Verify the call to btg_app_service
        # The first argument to generate_xhtml_from_content_items is the DTO
        call_args = self.mock_btg_app_service.generate_xhtml_from_content_items.call_args[0][0]
        self.assertIsInstance(call_args, XhtmlGenerationRequestDTO)
        self.assertEqual(call_args.id_prefix, test_id_prefix)
        self.assertEqual(call_args.content_items, test_content_items)
        self.assertEqual(call_args.target_language, test_target_lang)
        self.assertEqual(call_args.prompt_instructions, test_prompt_instr) # This is the EBTG level prompt
        self.assertIn("translated_xhtml_content", call_args.response_schema_for_gemini["properties"])


    def test_generate_xhtml_btg_reports_error(self):
        test_id_prefix = "error_doc"
        test_content_items = [{"type": "text", "data": "Error case"}]

        self.mock_btg_app_service.generate_xhtml_from_content_items.return_value = XhtmlGenerationResponseDTO(
            id_prefix=test_id_prefix,
            error_message="BTG API failed"
        )

        result_xhtml = self.integration_service.generate_xhtml(
            id_prefix=test_id_prefix,
            content_items=test_content_items,
            target_language="es",
            prompt_instructions="Translate to Spanish"
        )
        self.assertIsNone(result_xhtml)

    def test_generate_xhtml_btg_service_exception(self):
        test_id_prefix = "exception_doc"
        test_content_items = [{"type": "text", "data": "Exception case"}]

        self.mock_btg_app_service.generate_xhtml_from_content_items.side_effect = ApiXhtmlGenerationError("BTG Service Exception")

        with self.assertRaises(ApiXhtmlGenerationError):
            self.integration_service.generate_xhtml(
                id_prefix=test_id_prefix,
                content_items=test_content_items,
                target_language="de",
                prompt_instructions="Translate to German"
            )

    def test_btg_translation_service_not_initialized(self):
        # Simulate translation_service not being ready in BTG
        self.mock_btg_app_service.translation_service = None 

        with self.assertRaisesRegex(ApiXhtmlGenerationError, "BTG module's TranslationService not ready"):
            self.integration_service.generate_xhtml(
                id_prefix="no_ts_doc",
                content_items=[{"type": "text", "data": "Some text"}],
                target_language="ko",
                prompt_instructions="Translate this."
            )

if __name__ == '__main__':
    unittest.main()
