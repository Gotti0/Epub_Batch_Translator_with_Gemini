# ebtg/config_manager.py
import json
from pathlib import Path
from typing import Dict, Any, Optional

DEFAULT_EBTG_CONFIG_FILENAME = "ebtg_config.json"

class EbtgConfigManager:
    def __init__(self, config_file_path: Optional[str] = None):
        self.config_file_path = Path(config_file_path) if config_file_path else Path(DEFAULT_EBTG_CONFIG_FILENAME)

    def get_default_config(self) -> Dict[str, Any]:
        return {
            "target_language": "ko",
            "universal_translation_prompt": (
                "You are a professional translator. Translate the given text into {target_language}. "
                "If the input is structured (like content items for XHTML), maintain the structure, "
                "translate textual data, and preserve image sources. "
                "For plain text, provide a direct translation. "
                "Refer to the LOREBOOK_CONTEXT if provided. "
                "Text to translate or content items: {{content_items}} "
                "LOREBOOK_CONTEXT: {{lorebook_context}}"
            ),
            "btg_config_path": None, # Path to btg_module's config.json, or None to use BTG's default
            # "content_segmentation_max_items": 0, # Replaced by xhtml_segment_target_chars
            "xhtml_segment_target_chars": 4000, # Target character length for XHTML content items per segment. 0 or negative means no char-based segmentation.
            "perform_epub_validation": True, # New option to control EPUB validation
            "perform_content_omission_check": True # New option for content omission check
     }

    def load_config(self) -> Dict[str, Any]:
        default_cfg = self.get_default_config()
        if self.config_file_path.exists():
            try:
                with open(self.config_file_path, 'r', encoding='utf-8') as f:
                    user_cfg = json.load(f)
                default_cfg.update(user_cfg)
            except Exception as e:
                print(f"Warning: Could not load EBTG config '{self.config_file_path}': {e}. Using defaults.")
        else:
            print(f"Info: EBTG config file '{self.config_file_path}' not found. Using default EBTG settings.")
        return default_cfg

    def save_config(self, config_data: Dict[str, Any]):
        try:
            with open(self.config_file_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error: Could not save EBTG config '{self.config_file_path}': {e}")