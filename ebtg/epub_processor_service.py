# c:\Users\Hyunwoo_Room\Downloads\EBTG_Project\ebtg\epub_processor_service.py
import os
from ebooklib import epub
from typing import List, Dict, Any, Optional

# DTOs and Exceptions are expected to be in these locations
from btg_module.logger_config import setup_logger
from .ebtg_dtos import XhtmlGenerationRequest, XhtmlGenerationResponse
# from .ebtg_logger import EbtgLogger # Assuming a logger is available
from .ebtg_exceptions import EbtgFileProcessingError, XhtmlExtractionError, ApiXhtmlGenerationError

module_logger = setup_logger(__name__)

# --- Dummy/Placeholder Implementations (to be replaced later) ---
class SimplifiedHtmlExtractor:
    """
    (Placeholder) Extracts content items from XHTML.
    The actual implementation is in ebtg_simplified_html_extractor.py
    """
    def __init__(self):
        self.logger = setup_logger(self.__class__.__name__ + ".dummy")

    def extract_content(self, xhtml_content: str, file_name: str) -> List[Dict[str, Any]]:
        self.logger.log_debug(f"[SIMULATED] SimplifiedHtmlExtractor: Extracting from {file_name}")
        # Simulate extracting a text block and an image
        return [
            {"type": "text", "data": f"This is sample text from {file_name}."},
            {"type": "image", "data": {"src": "../images/example_image.png", "alt": "Original alt text for image"}}
        ]

class BtgIntegrationService:
    """
    (Placeholder) Integrates with BTG module for XHTML generation.
    To be implemented in its own module (e.g., ebtg_btg_integration_service.py).
    """
    def __init__(self):
        self.logger = setup_logger(self.__class__.__name__ + ".dummy")

    def generate_xhtml_via_api(self, request: XhtmlGenerationRequest) -> XhtmlGenerationResponse:
        self.logger.log_debug(f"[SIMULATED] BtgIntegrationService: Calling BTG API for {request.id_prefix} to {request.target_language}")

        if "error_trigger" in request.id_prefix: # For testing error handling
            self.logger.log_warning(f"[SIMULATED] BtgIntegrationService: Simulating API error for {request.id_prefix}")
            return XhtmlGenerationResponse(id_prefix=request.id_prefix, errors="Simulated API generation error.")

        body_content_parts = []
        for item in request.content_items:
            if item["type"] == "text":
                # Simulate translation by appending language code
                body_content_parts.append(f"<p>{item['data']} [{request.target_language.upper()}]</p>")
            elif item["type"] == "image":
                # Simulate alt text translation
                translated_alt = f"{item['data']['alt']} [{request.target_language.upper()}]"
                body_content_parts.append(f"<img src=\"{item['data']['src']}\" alt=\"{translated_alt}\"/>")

        full_body_content = "\n    ".join(body_content_parts)
        simulated_xhtml = f"""<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{request.target_language}" lang="{request.target_language}">
<head>
    <meta charset="utf-8"/>
    <title>Translated {request.id_prefix}</title>
</head>
<body>
    <h1>Content for {request.id_prefix}</h1>
    {full_body_content}
</body>
</html>"""
        return XhtmlGenerationResponse(id_prefix=request.id_prefix, generated_xhtml_string=simulated_xhtml)

# --- Main Service Implementation ---
class EpubProcessorService:
    def __init__(self,
                 html_extractor: SimplifiedHtmlExtractor,
                 btg_service: BtgIntegrationService):
        self.logger = module_logger # EpubProcessorService uses the module-level logger
        self.html_extractor = html_extractor
        self.btg_service = btg_service
        self.default_prompt_instructions = (
            "Please translate the following text segments into {target_language}. "
            "For any image items, also translate their 'alt' text. "
            "Construct a complete and valid XHTML document string using the translated text and image information. "
            "Place the images according to their original sequence relative to the text blocks. "
            "Wrap text paragraphs in <p> tags. Ensure the image 'src' attributes are preserved exactly as provided. "
            "The generated XHTML should be well-formed."
        )

    def _get_xhtml_documents_in_order(self, book: epub.EpubBook) -> List[epub.EpubHtml]:
        """Retrieves XHTML documents from the EPUB book based on the spine order."""
        xhtml_docs = []
        if not book.spine:
            self.logger.log_warning("EPUB spine is empty or not defined.")
            return []

        for spine_item_tuple in book.spine:
            item_id = spine_item_tuple[0]
            item = book.get_item_with_id(item_id)
            if item and item.get_type() == epub.ITEM_DOCUMENT:
                if isinstance(item, epub.EpubHtml):
                    xhtml_docs.append(item)
                else:
                    self.logger.log_warning(f"Spine item '{item.get_name()}' (ID: {item_id}) is ITEM_DOCUMENT but not EpubHtml. "
                                       f"Creating EpubHtml wrapper for processing.")
                    temp_html_item = epub.EpubHtml(uid=item.id, file_name=item.file_name, media_type=item.media_type)
                    temp_html_item.content = item.content # content is bytes
                    xhtml_docs.append(temp_html_item)
            # Non-document items in spine are ignored for content processing
        return xhtml_docs

    def _recursively_update_toc_links(self, toc_entry: Any, new_book: epub.EpubBook) -> Optional[Any]:
        """Helper to update TOC links to point to items in the new book."""
        if isinstance(toc_entry, epub.Link):
            original_href_base = toc_entry.href.split('#')[0]
            anchor = toc_entry.href.split('#')[1] if '#' in toc_entry.href else None
            new_item = new_book.get_item_with_href(original_href_base)
            if new_item:
                new_href = new_item.file_name
                if anchor:
                    new_href += f"#{anchor}"
                return epub.Link(href=new_href, title=toc_entry.title, uid=getattr(toc_entry, 'uid', None))
            else:
                self.logger.log_warning(f"TOC link target '{original_href_base}' not found in new book. Skipping TOC entry: {toc_entry.title}")
                return None
        elif isinstance(toc_entry, tuple) and len(toc_entry) == 2: # Section: (title_or_section_obj, [children])
            section_title_obj = toc_entry[0]
            section_title_str = section_title_obj.title if isinstance(section_title_obj, epub.Section) else str(section_title_obj)
            
            new_children = []
            for child_entry in toc_entry[1]:
                updated_child = self._recursively_update_toc_links(child_entry, new_book)
                if updated_child:
                    new_children.append(updated_child)
            
            if new_children:
                if isinstance(section_title_obj, epub.Section):
                    # Try to preserve section's own href if it exists and can be mapped
                    new_section_href = section_title_obj.href
                    if section_title_obj.href:
                        section_href_base = section_title_obj.href.split('#')[0]
                        section_anchor = section_title_obj.href.split('#')[1] if '#' in section_title_obj.href else None
                        mapped_section_item = new_book.get_item_with_href(section_href_base)
                        if mapped_section_item:
                            new_section_href = mapped_section_item.file_name
                            if section_anchor: new_section_href += f"#{section_anchor}"
                        else:
                            self.logger.log_warning(f"TOC Section '{section_title_str}' href '{section_title_obj.href}' not found in new book. Using original.")
                    
                    new_section = epub.Section(section_title_str, href=new_section_href)
                    return (new_section, new_children)
                return (section_title_str, new_children)
            else:
                self.logger.log_warning(f"TOC section '{section_title_str}' has no valid children after update. Skipping section.")
                return None
        else:
            self.logger.log_warning(f"Unknown TOC entry type: {type(toc_entry)}. Skipping.")
            return None

    def process_epub(self, input_epub_path: str, output_epub_path: str, target_language: str,
                     prompt_instructions_override: Optional[str] = None):
        self.logger.log_info(f"Starting EPUB processing for: {input_epub_path} -> {output_epub_path} (Lang: {target_language})")
        if not os.path.exists(input_epub_path):
            raise EbtgFileProcessingError(f"Input EPUB file not found: {input_epub_path}")

        try:
            original_book = epub.read_epub(input_epub_path)
        except Exception as e:
            raise EbtgFileProcessingError(f"Failed to read EPUB file {input_epub_path}", original_exception=e)

        new_book = epub.EpubBook()

        # 1. Copy metadata
        if original_book.get_metadata('DC', 'identifier'):
            new_book.set_identifier(original_book.get_metadata('DC', 'identifier')[0][0] + f"_translated_{target_language}")
        else:
            new_book.set_identifier(f"urn:uuid:ebtg-generated-{os.path.basename(input_epub_path)}-{target_language}")

        original_title = "Untitled"
        if original_book.get_metadata('DC', 'title'):
            original_title = original_book.get_metadata('DC', 'title')[0][0]
        new_book.set_title(f"{original_title} ({target_language.upper()})")
        new_book.set_language(target_language)

        for ns, meta_dict in original_book.metadata.items():
            for key, value_list in meta_dict.items():
                if ns == 'DC' and key in ['identifier', 'title', 'language']: continue
                for value_tuple in value_list:
                    new_book.add_metadata(ns, key, value_tuple[0], others=value_tuple[1] if len(value_tuple) > 1 else {})
        
        # 2. Get XHTML documents in order
        xhtml_docs_original = self._get_xhtml_documents_in_order(original_book)
        self.logger.log_info(f"Found {len(xhtml_docs_original)} XHTML documents in spine order.")

        original_to_new_item_map: Dict[epub.EpubItem, epub.EpubHtml] = {}

        for original_xhtml_doc in xhtml_docs_original:
            doc_filename = original_xhtml_doc.get_name()
            self.logger.log_info(f"Processing XHTML: {doc_filename}")
            original_content_str = original_xhtml_doc.get_content().decode('utf-8', errors='replace')

            # 3. Extract content items
            try:
                content_items = self.html_extractor.extract_content(original_content_str, doc_filename)
            except Exception as e:
                raise XhtmlExtractionError(f"Error extracting content from {doc_filename}", original_exception=e, details={"filename": doc_filename})

            # 4. Generate new XHTML via BTG (simulated)
            prompt = (prompt_instructions_override or self.default_prompt_instructions).format(target_language=target_language)
            req_dto = XhtmlGenerationRequest(doc_filename, content_items, target_language, prompt)
            
            generated_xhtml_str = original_content_str # Default to original if API fails
            try:
                res_dto = self.btg_service.generate_xhtml_via_api(req_dto)
                if res_dto.errors:
                    self.logger.log_error(f"API generation failed for {doc_filename}: {res_dto.errors}. Using original content.")
                elif res_dto.generated_xhtml_string is not None:
                    generated_xhtml_str = res_dto.generated_xhtml_string
                    self.logger.log_info(f"Successfully generated XHTML for {doc_filename} via API.")
                else: # Should not happen if errors is None
                     self.logger.log_warning(f"API response for {doc_filename} had no errors but no XHTML string. Using original.")
            except Exception as e: # Catch broader exceptions from the service call itself
                self.logger.log_error(f"Error calling BtgIntegrationService for {doc_filename}: {e}. Using original content.", exc_info=True)
                # Consider raising ApiXhtmlGenerationError here if it's a critical failure mode

            new_xhtml_item = epub.EpubHtml(
                uid=original_xhtml_doc.id or f"uid_{doc_filename.replace('.', '_')}",
                file_name=original_xhtml_doc.file_name, # Crucial: use the same href
                lang=target_language,
                title=original_xhtml_doc.title or doc_filename.split('.')[0]
            )
            new_xhtml_item.set_content(generated_xhtml_str.encode('utf-8'))
            new_book.add_item(new_xhtml_item)
            original_to_new_item_map[original_xhtml_doc] = new_xhtml_item

        # 5. Copy other resources (CSS, images, fonts)
        for item in original_book.get_items():
            if item.get_type() != epub.ITEM_DOCUMENT:
                if not new_book.get_item_with_href(item.file_name): # Avoid duplicates if manifest adds them
                    new_book.add_item(item)
                    self.logger.log_debug(f"Copied resource: {item.get_name()}")

        # 6. Rebuild spine
        new_spine = []
        if original_book.spine:
            for spine_entry in original_book.spine:
                original_item_id = spine_entry[0]
                linear_attr = spine_entry[1] if len(spine_entry) > 1 else 'yes' # Default linear to 'yes'
                
                original_item_obj = original_book.get_item_with_id(original_item_id)
                if original_item_obj in original_to_new_item_map:
                    new_spine.append((original_to_new_item_map[original_item_obj], linear_attr))
                else: # Item was not an XHTML doc we processed (e.g. cover.xhtml not in main flow, or non-doc item)
                    item_in_new_book = new_book.get_item_with_id(original_item_id) # Check if it was copied
                    if item_in_new_book:
                        new_spine.append((item_in_new_book, linear_attr))
                        self.logger.log_debug(f"Adding non-processed item {original_item_id} to new spine from copied resources.")
                    else:
                        self.logger.log_warning(f"Original spine item ID '{original_item_id}' not found in new book. Skipping from spine.")
        new_book.spine = new_spine

        # 7. Rebuild TOC
        new_toc_list = []
        for toc_entry in original_book.toc:
            updated_entry = self._recursively_update_toc_links(toc_entry, new_book)
            if updated_entry:
                new_toc_list.append(updated_entry)
        new_book.toc = tuple(new_toc_list)

        # Add NCX and Nav file
        new_book.add_item(epub.EpubNcx())
        new_book.add_item(epub.EpubNav())

        # 8. Write the new EPUB file
        try:
            epub.write_epub(output_epub_path, new_book, {})
            self.logger.log_info(f"Successfully created translated EPUB: {output_epub_path}")
        except Exception as e:
            raise EbtgFileProcessingError(f"Failed to write EPUB file {output_epub_path}", original_exception=e)
