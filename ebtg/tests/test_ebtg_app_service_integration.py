# ebtg/tests/test_ebtg_app_service_integration.py
import unittest
from unittest.mock import patch, MagicMock, call
from pathlib import Path

from ebtg.ebtg_app_service import EbtgAppService
from ebtg.epub_processor_service import EpubXhtmlItem
from btg_module.dtos import XhtmlGenerationRequestDTO, XhtmlGenerationResponseDTO # For mocking BTG's DTOs
from ebtg.ebtg_exceptions import ApiXhtmlGenerationError

# A minimal ebtg_config.json content for tests
MOCK_EBTG_CONFIG_CONTENT = {
    "target_language": "ko",
    "prompt_instructions_for_xhtml_generation": "Translate to Korean: {{content_items}}",
    "btg_config_path": "mock_btg_config.json" # Path to a dummy or mocked BTG config
}
MOCK_EBTG_CONFIG_CONTENT_WITH_SEGMENTATION = {
    "target_language": "ko",
    "prompt_instructions_for_xhtml_generation": "Translate this full document.",
    "prompt_instructions_for_xhtml_fragment_generation": "Translate this fragment. Overall task: '{overall_task_description}'. Items:",
    "btg_config_path": "mock_btg_config.json",
    "content_segmentation_max_items": 2 # Enable segmentation for testing
}
# A minimal btg_module/config.json content for tests (if BTG AppService tries to load it)
MOCK_BTG_CONFIG_CONTENT = {
    "api_key": "TEST_API_KEY_DO_NOT_USE", # Dummy key
    "model_name": "gemini-test-model",
    "xhtml_generation_max_chars_per_batch": 10000 # Example value
}

class TestEbtgAppServiceIntegration(unittest.TestCase):

    @patch('ebtg.ebtg_app_service.EbtgConfigManager')
    @patch('ebtg.ebtg_app_service.BtgAppService') # Mock BTG's AppService
    @patch('ebtg.ebtg_app_service.EpubProcessorService')
    @patch('ebtg.ebtg_app_service.SimplifiedHtmlExtractor')
    @patch('ebtg.ebtg_app_service.BtgIntegrationService') # Mock EBTG's BtgIntegrationService
    @patch('ebtg.ebtg_app_service.ContentSegmentationService')
    def setUp(self, MockContentSegmentationService, MockBtgIntegrationService, MockSimplifiedHtmlExtractor, MockEpubProcessorService, MockBtgAppService, MockEbtgConfigManager):
        # Mock EbtgConfigManager
        self.mock_ebtg_config_manager_instance = MockEbtgConfigManager.return_value
        self.mock_ebtg_config_manager_instance.load_config.return_value = MOCK_EBTG_CONFIG_CONTENT.copy()

        # Mock BtgAppService (from btg_module)
        self.mock_btg_app_service_instance = MockBtgAppService.return_value
        # Crucially, ensure the translation_service attribute exists on the mock BtgAppService instance
        # because BtgIntegrationService checks for it.
        self.mock_btg_app_service_instance.translation_service = MagicMock()
        self.mock_btg_app_service_instance.config = MOCK_BTG_CONFIG_CONTENT.copy() # Provide mock config

        # Mock BtgIntegrationService (from ebtg package)
        self.mock_btg_integration_instance = MockBtgIntegrationService.return_value

        # Mock EpubProcessorService
        self.mock_epub_processor_instance = MockEpubProcessorService.return_value

        # Mock SimplifiedHtmlExtractor
        self.mock_html_extractor_instance = MockSimplifiedHtmlExtractor.return_value

        # Mock ContentSegmentationService
        self.mock_content_segmenter_instance = MockContentSegmentationService.return_value
        # Default behavior for segmenter: return the content_items as a single segment
        # This ensures item_segments is not empty for most tests.
        self.mock_content_segmenter_instance.segment_content_items.side_effect = \
            lambda ci, fn, max_items: [ci] if ci else []

        # Initialize EbtgAppService with mocked dependencies
        # The config_path argument to EbtgAppService is used by EbtgConfigManager, which is mocked.
        self.app_service = EbtgAppService(config_path="dummy_ebtg_config.json")

    def test_translate_epub_single_file_success(self):
        input_epub = "test_input.epub"
        output_epub = "test_output.epub"

        # Setup EpubProcessorService mock
        xhtml_item1_content = "<body><p>Hello</p><img src='img.png' alt='An image'></body>"
        xhtml_item1 = EpubXhtmlItem(filename="file1.xhtml", item_id="id1", original_content_bytes=xhtml_item1_content.encode('utf-8'))
        self.mock_epub_processor_instance.get_xhtml_items.return_value = [xhtml_item1]

        # Setup SimplifiedHtmlExtractor mock
        extracted_content1 = [{"type": "text", "data": "Hello"}, {"type": "image", "data": {"src": "img.png", "alt": "An image"}}]
        self.mock_html_extractor_instance.extract_content.return_value = extracted_content1

        # Setup BtgIntegrationService mock to return generated XHTML
        generated_xhtml1 = "<?xml version='1.0' encoding='utf-8'?><html xmlns='http://www.w3.org/1999/xhtml'><head><title>Translated file1.xhtml</title></head><body><p>안녕하세요</p><img src='img.png' alt='이미지'/></body></html>"
        self.mock_btg_integration_instance.generate_xhtml.return_value = generated_xhtml1

        # Call the method under test
        self.app_service.translate_epub(input_epub, output_epub)

        # Assertions
        self.mock_epub_processor_instance.open_epub.assert_called_once_with(input_epub)
        self.mock_epub_processor_instance.get_xhtml_items.assert_called_once()
        self.mock_html_extractor_instance.extract_content.assert_called_once_with(xhtml_item1_content)

        self.mock_btg_integration_instance.generate_xhtml.assert_called_once_with(
            id_prefix="file1.xhtml",
            content_items=extracted_content1,
            target_language=MOCK_EBTG_CONFIG_CONTENT["target_language"],
            prompt_instructions=MOCK_EBTG_CONFIG_CONTENT["prompt_instructions_for_xhtml_generation"]
        )
        self.mock_epub_processor_instance.update_xhtml_content.assert_called_once_with(
            "id1", generated_xhtml1.encode('utf-8')
        )
        self.mock_epub_processor_instance.save_epub.assert_called_once_with(output_epub)

    def test_translate_epub_xhtml_generation_fails_keeps_original(self):
        input_epub = "test_input_fail.epub"
        output_epub = "test_output_fail.epub"

        xhtml_item1_content = "<body><p>Original Content</p></body>"
        xhtml_item1 = EpubXhtmlItem(filename="fail.xhtml", item_id="id_fail", original_content_bytes=xhtml_item1_content.encode('utf-8'))
        self.mock_epub_processor_instance.get_xhtml_items.return_value = [xhtml_item1]

        extracted_content1 = [{"type": "text", "data": "Original Content"}]
        self.mock_html_extractor_instance.extract_content.return_value = extracted_content1

        # Simulate BtgIntegrationService returning None (failure)
        self.mock_btg_integration_instance.generate_xhtml.return_value = None

        self.app_service.translate_epub(input_epub, output_epub)

        # Verify that update_xhtml_content was NOT called with new content,
        # implying original content is kept (EpubProcessorService handles this internally by not changing the item if not updated)
        # A more direct test would be to check the content map in a real EpubProcessorService,
        # but with mocking, we check that no *update* call for new content happened for this item.
        # The current EpubProcessorService mock doesn't allow easy checking of "kept original",
        # so we verify update_xhtml_content was NOT called for this item with *new* content.
        # If it was called, it would be with the original content if that's the fallback.
        # The current EbtgAppService logic for failure is to log and *not* call update_xhtml_content.
        self.mock_epub_processor_instance.update_xhtml_content.assert_not_called()
        self.mock_epub_processor_instance.save_epub.assert_called_once_with(output_epub)

    def test_img_src_preserved_alt_translated_and_order(self):
        # This test focuses on the data flow and expected output structure,
        # assuming the (mocked) BtgIntegrationService correctly instructs the LLM.
        input_epub = "test_img.epub"
        output_epub = "test_img_out.epub"

        original_xhtml = "<body><p>Text before.</p><img src='../images/pic.jpg' alt='A picture of a cat.'/><p>Text after.</p></body>"
        xhtml_item = EpubXhtmlItem(filename="img_test.xhtml", item_id="img_id1", original_content_bytes=original_xhtml.encode('utf-8'))
        self.mock_epub_processor_instance.get_xhtml_items.return_value = [xhtml_item]

        extracted_items = [
            {"type": "text", "data": "Text before."},
            {"type": "image", "data": {"src": "../images/pic.jpg", "alt": "A picture of a cat."}},
            {"type": "text", "data": "Text after."}
        ]
        self.mock_html_extractor_instance.extract_content.return_value = extracted_items

        # Mocked API output - this is what we expect the LLM to generate given the prompt and content_items
        # The key is that BtgIntegrationService should construct a prompt that leads to this.
        # The test here verifies EbtgAppService handles this *returned* XHTML correctly.
        mocked_api_generated_xhtml = (
            "<?xml version='1.0' encoding='utf-8'?>"
            "<html xmlns='http://www.w3.org/1999/xhtml'>"
            "<head><title>Translated img_test.xhtml</title></head>"
            "<body>"
            "<p>번역된 이전 텍스트.</p>"
            "<img src='../images/pic.jpg' alt='고양이 사진.'/>"  # src preserved, alt translated
            "<p>번역된 이후 텍스트.</p>"
            "</body></html>"
        )
        self.mock_btg_integration_instance.generate_xhtml.return_value = mocked_api_generated_xhtml

        self.app_service.translate_epub(input_epub, output_epub)

        # Check that BtgIntegrationService was called with the correct content_items
        args, kwargs = self.mock_btg_integration_instance.generate_xhtml.call_args
        self.assertEqual(kwargs['content_items'], extracted_items)

        # Check that EpubProcessorService.update_xhtml_content was called with the mocked API output
        self.mock_epub_processor_instance.update_xhtml_content.assert_called_once_with(
            "img_id1", mocked_api_generated_xhtml.encode('utf-8')
        )

        # Note: Verifying the *content* of the prompt sent to the actual LLM
        # would be part of test_btg_integration_service.py or deeper into btg_module tests.
        # This test confirms EbtgAppService correctly uses its components and handles
        # the (mocked) API-generated XHTML.

    def test_translate_epub_with_multiple_images_and_text_order(self):
        input_epub = "test_multi_img.epub"
        output_epub = "test_multi_img_out.epub"

        original_xhtml = """<body>
            <p>Text 1</p>
            <img src='img1.png' alt='Image 1'/>
            <p>Text 2</p>
            <img src='img2.jpeg' alt='Image 2'/>
            <p>Text 3</p>
        </body>"""
        xhtml_item = EpubXhtmlItem(filename="multi.xhtml", item_id="multi_id", original_content_bytes=original_xhtml.encode('utf-8'))
        self.mock_epub_processor_instance.get_xhtml_items.return_value = [xhtml_item]

        extracted_items = [
            {"type": "text", "data": "Text 1"},
            {"type": "image", "data": {"src": "img1.png", "alt": "Image 1"}},
            {"type": "text", "data": "Text 2"},
            {"type": "image", "data": {"src": "img2.jpeg", "alt": "Image 2"}},
            {"type": "text", "data": "Text 3"}
        ]
        self.mock_html_extractor_instance.extract_content.return_value = extracted_items

        mocked_api_generated_xhtml = (
            "<?xml version='1.0' encoding='utf-8'?>"
            "<html xmlns='http://www.w3.org/1999/xhtml'>"
            "<head><title>Translated multi.xhtml</title></head>"
            "<body>"
            "<p>텍스트 1</p>"
            "<img src='img1.png' alt='이미지 1'/>"
            "<p>텍스트 2</p>"
            "<img src='img2.jpeg' alt='이미지 2'/>"
            "<p>텍스트 3</p>"
            "</body></html>"
        )
        self.mock_btg_integration_instance.generate_xhtml.return_value = mocked_api_generated_xhtml

        self.app_service.translate_epub(input_epub, output_epub)

        args, kwargs = self.mock_btg_integration_instance.generate_xhtml.call_args
        self.assertEqual(kwargs['content_items'], extracted_items) # Check order
        self.mock_epub_processor_instance.update_xhtml_content.assert_called_once_with(
            "multi_id", mocked_api_generated_xhtml.encode('utf-8')
        )

    def test_translate_epub_xhtml_not_well_formed(self):
        input_epub = "test_bad_xml.epub"
        output_epub = "test_bad_xml_out.epub"

        xhtml_item_content = "<body><p>Content</p></body>"
        xhtml_item = EpubXhtmlItem(filename="bad.xhtml", item_id="bad_id", original_content_bytes=xhtml_item_content.encode('utf-8'))
        self.mock_epub_processor_instance.get_xhtml_items.return_value = [xhtml_item]

        extracted_content = [{"type": "text", "data": "Content"}]
        self.mock_html_extractor_instance.extract_content.return_value = extracted_content

        # Simulate API returning non-well-formed XML
        malformed_xhtml = "<html><body><p>안녕하세요<br></body></html>" # Missing closing p, br not self-closed for XHTML
        self.mock_btg_integration_instance.generate_xhtml.return_value = malformed_xhtml

        self.app_service.translate_epub(input_epub, output_epub)

        # Original content should be kept, so update_xhtml_content should not be called with new content
        self.mock_epub_processor_instance.update_xhtml_content.assert_not_called()
        self.mock_epub_processor_instance.save_epub.assert_called_once_with(output_epub)

    @patch('ebtg.ebtg_app_service.ContentSegmentationService') # Mock ContentSegmentationService specifically for this test
    def test_translate_epub_with_content_segmentation(self, MockContentSegmentationServiceInstance):
        # Re-initialize app_service with config that enables segmentation
        # self.mock_ebtg_config_manager_instance.load_config.return_value = MOCK_EBTG_CONFIG_CONTENT_WITH_SEGMENTATION.copy() # This is for the mock manager
        # self.app_service = EbtgAppService(config_path="dummy_ebtg_config_segment.json") # Don't re-initialize
        
        # Directly set the config for the existing app_service instance for this test
        self.app_service.config = MOCK_EBTG_CONFIG_CONTENT_WITH_SEGMENTATION.copy()
        self.app_service.content_segmenter = MockContentSegmentationServiceInstance # Use the one passed to this test method

        input_epub = "test_segmented.epub"
        output_epub = "test_segmented_out.epub"

        original_xhtml = "<body><p>Text 1</p><img src='img1.png' alt='Image 1'/><p>Text 2</p><img src='img2.jpeg' alt='Image 2'/><p>Text 3</p></body>"
        xhtml_item = EpubXhtmlItem(filename="segment.xhtml", item_id="seg_id", original_content_bytes=original_xhtml.encode('utf-8'))
        self.mock_epub_processor_instance.get_xhtml_items.return_value = [xhtml_item]

        extracted_items_full = [
            {"type": "text", "data": "Text 1"}, {"type": "image", "data": {"src": "img1.png", "alt": "Image 1"}},
            {"type": "text", "data": "Text 2"}, {"type": "image", "data": {"src": "img2.jpeg", "alt": "Image 2"}},
            {"type": "text", "data": "Text 3"}
        ]
        self.mock_html_extractor_instance.extract_content.return_value = extracted_items_full

        # Mock ContentSegmentationService to return 2 segments
        segment1_items = extracted_items_full[:2] # Text 1, Image 1
        segment2_items = extracted_items_full[2:] # Text 2, Image 2, Text 3
        MockContentSegmentationServiceInstance.segment_content_items.return_value = [segment1_items, segment2_items]

        # Mock BtgIntegrationService to return XHTML fragments
        fragment1_xhtml = "<p>텍스트 1</p><img src='img1.png' alt='이미지 1'/>"
        fragment2_xhtml = "<p>텍스트 2</p><img src='img2.jpeg' alt='이미지 2'/><p>텍스트 3</p>"
        self.mock_btg_integration_instance.generate_xhtml.side_effect = [fragment1_xhtml, fragment2_xhtml]

        self.app_service.translate_epub(input_epub, output_epub)

        # Verify BtgIntegrationService calls
        self.assertEqual(self.mock_btg_integration_instance.generate_xhtml.call_count, 2)
        calls = self.mock_btg_integration_instance.generate_xhtml.call_args_list
        
        # Call 1 (fragment)
        self.assertEqual(calls[0][1]['id_prefix'], "segment_part_1.xhtml")
        self.assertEqual(calls[0][1]['content_items'], segment1_items)
        self.assertIn("Translate this fragment.", calls[0][1]['prompt_instructions'])
        self.assertIn(MOCK_EBTG_CONFIG_CONTENT_WITH_SEGMENTATION["prompt_instructions_for_xhtml_generation"], calls[0][1]['prompt_instructions'])

        # Call 2 (fragment)
        self.assertEqual(calls[1][1]['id_prefix'], "segment_part_2.xhtml")
        self.assertEqual(calls[1][1]['content_items'], segment2_items)
        self.assertIn("Translate this fragment.", calls[1][1]['prompt_instructions'])

        # Verify final assembled XHTML
        expected_assembled_xhtml_body = f"{fragment1_xhtml}\n{fragment2_xhtml}"
        expected_full_xhtml = self.app_service._wrap_body_fragments_in_full_xhtml(expected_assembled_xhtml_body, "segment", "ko")
        self.mock_epub_processor_instance.update_xhtml_content.assert_called_once_with("seg_id", expected_full_xhtml.encode('utf-8'))
        self.mock_epub_processor_instance.save_epub.assert_called_once_with(output_epub)

if __name__ == '__main__':
    unittest.main()
