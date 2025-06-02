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
            "prompt_instructions_for_xhtml_generation": (
                "Translate the following text blocks and integrate the image information "
                "to create a complete and valid XHTML document. "
                "Preserve image sources and translate alt text if present. "
                "Wrap paragraphs in <p> tags. Ensure the output is a single, "
                "well-formed XHTML string."
            ),
            "btg_config_path": None, # Path to btg_module's config.json, or None to use BTG's default
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