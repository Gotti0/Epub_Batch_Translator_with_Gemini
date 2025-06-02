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

        # ebtg_config is not directly used by BtgIntegrationService for prompt construction in the new setup,
        # as prompt_instructions are passed directly to generate_xhtml.
        self.ebtg_config = {} # Minimal config, specific values passed in tests.
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
        
        # Verify enhanced prompt construction
        self.assertIn(test_prompt_instr, call_args.prompt_instructions)
        self.assertIn("Image Placement:", call_args.prompt_instructions)
        self.assertIn("Basic Block Structure:", call_args.prompt_instructions)
        self.assertIn("Novel Dialogue Formatting:", call_args.prompt_instructions)
        self.assertIn("Novel-Specific Formatting Details:", call_args.prompt_instructions) # Phase 3
        self.assertIn("Illustrative Few-Shot Examples", call_args.prompt_instructions) # Phase 3
        
        # Check that the base prompt is at the beginning of the enhanced prompt
        self.assertTrue(call_args.prompt_instructions.startswith(test_prompt_instr))

        # Check specific phrases from enhancement prompts
        self.assertIn("Images (represented by {'type': 'image', ...} items", call_args.prompt_instructions)
        self.assertIn("Ensure consistent use of fundamental HTML block-level tags", call_args.prompt_instructions)
        self.assertIn("For dialogue sections, if they can be identified", call_args.prompt_instructions)
        # Phase 3 checks
        self.assertIn("Each distinct spoken line, including those starting with quotation marks", call_args.prompt_instructions)
        self.assertIn("Example 1 (Text Only):", call_args.prompt_instructions)

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

    def test_prompt_enhancements_are_included(self):
        test_id_prefix = "prompt_test"
        test_content_items = [{"type": "text", "data": "Check prompts"}]
        test_target_lang = "en"
        base_prompt = "Base instructions for testing."

        # Mock the call to btg_app_service to prevent actual API call, just inspect the DTO
        self.mock_btg_app_service.generate_xhtml_from_content_items.return_value = XhtmlGenerationResponseDTO(
            id_prefix=test_id_prefix,
            generated_xhtml_string="<p>Checked</p>"
        )

        self.integration_service.generate_xhtml(
            id_prefix=test_id_prefix,
            content_items=test_content_items,
            target_language=test_target_lang,
            prompt_instructions=base_prompt
        )

        # Verify the call and inspect the DTO passed
        self.mock_btg_app_service.generate_xhtml_from_content_items.assert_called_once()
        request_dto_arg = self.mock_btg_app_service.generate_xhtml_from_content_items.call_args[0][0]

        self.assertIsInstance(request_dto_arg, XhtmlGenerationRequestDTO)
        self.assertTrue(request_dto_arg.prompt_instructions.startswith(base_prompt))
        self.assertIn("Image Placement: Images (represented by {'type': 'image', ...} items", request_dto_arg.prompt_instructions)
        self.assertIn("Basic Block Structure: Ensure consistent use of fundamental HTML block-level tags.", request_dto_arg.prompt_instructions)
        self.assertIn("Novel Dialogue Formatting: For dialogue sections, if they can be identified", request_dto_arg.prompt_instructions)
        self.assertIn("Novel-Specific Formatting Details:", request_dto_arg.prompt_instructions) # Phase 3
        self.assertIn("Illustrative Few-Shot Examples", request_dto_arg.prompt_instructions) # Phase 3


if __name__ == '__main__':
    unittest.main()
