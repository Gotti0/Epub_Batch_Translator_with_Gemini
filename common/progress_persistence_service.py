# ebtg/progress_persistence_service.py
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

PROGRESS_FILENAME_SUFFIX = "_ebtg_progress.json"

class ProgressPersistenceService:
    """
    Handles saving and loading the processing progress of XHTML files within an EPUB.
    This allows tracking which files were successfully processed, failed, or skipped.
    """

    def __init__(self):
        self.progress_data: Dict[str, Any] = {} # {epub_input_filename: {xhtml_filename: status}}
        logger.info("ProgressPersistenceService initialized.")

    def _get_progress_file_path(self, output_epub_path: str) -> Path:
        """Determines the path for the progress JSON file."""
        epub_output_path = Path(output_epub_path)
        # Place the progress file in the same directory as the output EPUB,
        # named after the output EPUB.
        progress_file_name = f"{epub_output_path.stem}{PROGRESS_FILENAME_SUFFIX}"
        return epub_output_path.parent / progress_file_name

    def record_xhtml_status(
        self, 
        epub_input_filename: str, 
        xhtml_filename: str, 
        status: str, # e.g., "success", "failed_extraction", "failed_api_generation", "skipped_empty"
        error_message: Optional[str] = None
    ):
        """
        Records the processing status for a specific XHTML file within an EPUB.
        """
        if epub_input_filename not in self.progress_data:
            self.progress_data[epub_input_filename] = {}
        
        entry = {"status": status}
        if error_message:
            entry["error"] = error_message
            
        self.progress_data[epub_input_filename][xhtml_filename] = entry
        logger.debug(f"Recorded progress for '{epub_input_filename}' -> '{xhtml_filename}': {status}")

    def save_progress(self, output_epub_path: str):
        """
        Saves the current progress data to a JSON file.
        The file is typically saved in the output directory of the processed EPUB.
        """
        if not self.progress_data:
            logger.info("No progress data to save.")
            return

        progress_file_path = self._get_progress_file_path(output_epub_path)
        try:
            progress_file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(progress_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.progress_data, f, indent=4, ensure_ascii=False)
            logger.info(f"Progress saved to: {progress_file_path}")
        except IOError as e:
            logger.error(f"Failed to save progress to {progress_file_path}: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred while saving progress: {e}", exc_info=True)

    def load_progress(self, output_epub_path: str) -> Dict[str, Any]:
        """
        Loads progress data from a JSON file.
        This can be used to check the status of previously processed files.
        """
        progress_file_path = self._get_progress_file_path(output_epub_path)
        if progress_file_path.exists():
            try:
                with open(progress_file_path, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                    # Merge with current data or replace, depending on strategy.
                    # For now, let's assume it replaces if called, or could be used to initialize.
                    self.progress_data = loaded_data 
                    logger.info(f"Progress loaded from: {progress_file_path}")
                    return loaded_data
            except (IOError, json.JSONDecodeError) as e:
                logger.error(f"Failed to load or parse progress from {progress_file_path}: {e}")
                return {} # Return empty if loading fails
            except Exception as e:
                logger.error(f"An unexpected error occurred while loading progress: {e}", exc_info=True)
                return {}
        else:
            logger.info(f"No progress file found at: {progress_file_path}")
            return {}
        
    def get_xhtml_status(self, epub_input_filename: str, xhtml_filename: str) -> Optional[Dict[str, str]]:
        """
        Retrieves the status of a specific XHTML file if it has been recorded.
        """
        return self.progress_data.get(epub_input_filename, {}).get(xhtml_filename)

    def clear_progress(self, epub_input_filename: Optional[str] = None):
        """
        Clears progress data. If epub_input_filename is provided, clears for that EPUB only.
        Otherwise, clears all progress data.
        """
        if epub_input_filename:
            if epub_input_filename in self.progress_data:
                del self.progress_data[epub_input_filename]
                logger.info(f"Cleared progress for EPUB: {epub_input_filename}")
            else:
                logger.info(f"No progress found to clear for EPUB: {epub_input_filename}")
        else:
            self.progress_data.clear()
            logger.info("Cleared all progress data.")

