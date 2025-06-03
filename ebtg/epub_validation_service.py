# ebtg/epub_validation_service.py
import logging
from pathlib import Path
from typing import Tuple, List

try:
    from epubcheck import EpubCheck
except ImportError:
    EpubCheck = None
    logging.getLogger(__name__).warning(
        "epubcheck-python library not found. EPUB validation will be skipped. "
        "Please install it via 'pip install epubcheck-python'."
    )

logger = logging.getLogger(__name__)

class EpubValidationService:
    def __init__(self):
        if EpubCheck is None:
            logger.warning("EpubValidationService initialized, but epubcheck library is missing. Validation will be disabled.")
        else:
            logger.info("EpubValidationService initialized.")

    def validate_epub(self, epub_file_path: str) -> Tuple[bool, List[str], List[str]]:
        """
        Validates the given EPUB file using epubcheck.

        Args:
            epub_file_path: Path to the EPUB file.

        Returns:
            A tuple: (is_valid, error_messages, warning_messages)
            is_valid: True if the EPUB has no errors, False otherwise.
            error_messages: A list of error messages from epubcheck.
            warning_messages: A list of warning messages from epubcheck.
        """
        if EpubCheck is None:
            logger.warning(f"Skipping EPUB validation for {epub_file_path} as epubcheck library is not available.")
            return True, [], ["EPUB validation skipped: epubcheck-python library not installed."]

        path_obj = Path(epub_file_path)
        if not path_obj.exists() or not path_obj.is_file():
            logger.error(f"EPUB validation failed: File not found at {epub_file_path}")
            return False, [f"File not found: {epub_file_path}"], []

        logger.info(f"Starting EPUB validation for: {epub_file_path}")
        errors: List[str] = []
        warnings: List[str] = []
        try:
            result = EpubCheck(str(path_obj)) # Ensure path is string

            for message_dict in result.messages:
                level = message_dict.get('level', 'UNKNOWN').upper()
                msg_text = message_dict.get('message', 'No message content.')
                file_info = message_dict.get('file', 'N/A')
                line_info = message_dict.get('line', 'N/A')
                col_info = message_dict.get('col', 'N/A')
                formatted_msg = f"[{level}] {msg_text} (File: {file_info}, Line: {line_info}, Col: {col_info})"
                if level == "ERROR": errors.append(formatted_msg)
                elif level == "WARNING": warnings.append(formatted_msg)
            return not errors, errors, warnings
        except Exception as e: # Catch general exceptions during EpubCheck execution
            logger.error(f"An unexpected error occurred during EPUB validation for {epub_file_path}: {e}", exc_info=True)
            return False, [f"Unexpected validation error: {str(e)}"], []