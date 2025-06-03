# ebtg/epub_processor_service.py
import logging
from pathlib import Path
from typing import List, Any, Dict, Optional
from dataclasses import dataclass
import ebooklib
from ebooklib import epub

logger = logging.getLogger(__name__)

@dataclass
class EpubXhtmlItem:
    filename: str
    item_id: Any # ebooklib item id
    original_content_bytes: bytes

@dataclass
class EpubResourceItem: # For CSS, images etc.
    filename: str
    item_id: Any
    content_bytes: bytes
    media_type: str


class EpubProcessorService:
    def __init__(self):
        self.book: Optional[epub.EpubBook] = None
        self._xhtml_items_cache: List[EpubXhtmlItem] = []
        self._other_resources_cache: List[EpubResourceItem] = []
        self._item_content_map: Dict[Any, bytes] = {} # Stores original or updated content

    def open_epub(self, epub_path: str) -> None:
        logger.info(f"Opening EPUB: {epub_path}")
        self.book = epub.read_epub(epub_path)
        self._xhtml_items_cache = []
        self._other_resources_cache = []
        self._item_content_map = {}

        if not self.book:
            raise FileNotFoundError(f"Could not read EPUB file: {epub_path}")

        for item in self.book.get_items():
            content = item.get_content()
            self._item_content_map[item.get_id()] = content # Store original content

            if item.get_type() == ebooklib.ITEM_DOCUMENT: # XHTML files
                self._xhtml_items_cache.append(
                    EpubXhtmlItem(
                        filename=item.get_name(), 
                        item_id=item.get_id(),
                        original_content_bytes=content
                    )
                )
            else: # CSS, images, fonts, etc.
                 self._other_resources_cache.append(
                    EpubResourceItem(
                        filename=item.get_name(),
                        item_id=item.get_id(),
                        content_bytes=content,
                        media_type=item.media_type
                    )
                )
        logger.info(f"EPUB opened. Found {len(self._xhtml_items_cache)} XHTML documents and {len(self._other_resources_cache)} other resources.")


    def get_xhtml_items(self) -> List[EpubXhtmlItem]:
        if not self.book:
            raise Exception("EPUB not opened yet.")
        return self._xhtml_items_cache

    def update_xhtml_content(self, item_id: Any, new_content_bytes: bytes) -> None:
        if not self.book:
            raise Exception("EPUB not opened yet.")
        
        if item_id in self._item_content_map:
            self._item_content_map[item_id] = new_content_bytes
            logger.debug(f"Content updated in map for item_id: {item_id}")
        else:
            logger.warning(f"Item ID {item_id} not found in content map for update.")


    def save_epub(self, output_epub_path: str) -> None:
        if not self.book:
            raise Exception("EPUB not opened or no content to save.")

        new_book = epub.EpubBook()
        
        for key in ['title', 'language', 'identifier', 'creator', 'contributor', 'publisher', 'rights', 'coverage', 'date', 'description', 'format', 'relation', 'source', 'subject', 'type']:
            metadata = self.book.get_metadata('DC', key)
            for m_value in metadata:
                new_book.add_metadata('DC', key, m_value[0], others=m_value[1] if len(m_value) > 1 else None)
        
        new_book.set_identifier(self.book.get_identifier())
        new_book.set_title(self.book.get_title())
        new_book.set_language(self.book.get_language())
        for author in self.book.get_metadata('DC', 'creator'):
            new_book.add_author(author[0])

        all_epub_items = []
        spine_items = [] 

        for item in self.book.get_items():
            item_id = item.get_id()
            filename = item.get_name()
            media_type = item.media_type
            content_to_write = self._item_content_map.get(item_id)

            if content_to_write is None:
                logger.warning(f"Content for item {filename} (ID: {item_id}) not found in map. Skipping.")
                continue

            new_item: Optional[epub.EpubItem] = None
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                new_item = epub.EpubHtml(title=Path(filename).stem, file_name=filename, lang=new_book.get_language() or 'en')
                new_item.set_content(content_to_write)
            else: # For all other items, create a generic EpubItem
                new_item = epub.EpubItem(uid=item_id, file_name=filename, media_type=media_type, content=content_to_write)

            if new_item:
                new_book.add_item(new_item)
                all_epub_items.append(new_item)

        original_spine_ids = [s[0].id for s in self.book.spine if isinstance(self.book.spine, list) and s] if self.book.spine else []
        new_items_by_id = {ni.get_id(): ni for ni in all_epub_items}

        for original_id in original_spine_ids:
            if original_id in new_items_by_id:
                spine_items.append(new_items_by_id[original_id])
            else:
                logger.warning(f"Original spine item with ID '{original_id}' not found in the new book's items. Omitting from spine.")
        
        new_book.spine = spine_items if spine_items else [item for item in all_epub_items if isinstance(item, epub.EpubHtml)]
        
        if not any(isinstance(i, epub.EpubNcx) for i in new_book.items):
             new_book.add_item(epub.EpubNcx())
        if not new_book.toc:
            new_book.toc = tuple(s_item for s_item in new_book.spine if isinstance(s_item, epub.EpubHtml))

        logger.info(f"Saving new EPUB to: {output_epub_path}")
        epub.write_epub(output_epub_path, new_book, {})
        logger.info("EPUB saved successfully.")