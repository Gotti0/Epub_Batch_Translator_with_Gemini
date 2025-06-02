# ebtg/cli/ebtg_cli.py
import logging
import argparse
from pathlib import Path
import sys
import inspect

# Add EBTG_Project root to sys.path to allow imports from ebtg and btg_module
current_file_path = Path(inspect.getfile(inspect.currentframe())).resolve()
ebtg_cli_dir = current_file_path.parent # EBTG_Project/ebtg/cli
ebtg_package_dir = ebtg_cli_dir.parent # EBTG_Project/ebtg
ebtg_project_root = ebtg_package_dir.parent # EBTG_Project

if str(ebtg_project_root) not in sys.path:
    sys.path.insert(0, str(ebtg_project_root))

try:
    from ebtg.ebtg_app_service import EbtgAppService
    from ebtg.ebtg_exceptions import EbtgProcessingError
    from ebtg.config_manager import EbtgConfigManager
except ImportError as e:
    print(f"Critical Import Error: {e}. Ensure the EBTG project structure is correct and PYTHONPATH is set up if necessary.")
    sys.exit(1)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    logger = logging.getLogger("EBTG_CLI")

    parser = argparse.ArgumentParser(description="EBTG - EPUB Batch Translator with Gemini (v7 API-XHTML)")
    parser.add_argument("input_epub", type=str, help="Path to the input EPUB file.")
    parser.add_argument("output_epub", type=str, help="Path to save the translated EPUB file.")
    parser.add_argument("--config", type=str, help="Path to EBTG configuration file (e.g., ebtg_config.json). Default: ebtg_config.json in current dir.", default=None)
    parser.add_argument("--btg_config", type=str, help="Path to BTG module's configuration file (e.g., btg_module/config.json). This path will be written into EBTG config if provided.", default=None)
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging.")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        for handler in logging.getLogger().handlers:
            handler.setLevel(logging.DEBUG)
        logger.info("Debug logging enabled.")

    ebtg_config_file_path = Path(args.config or "ebtg_config.json")

    # Ensure a default EBTG config exists if none is provided or specified one doesn't exist
    if not ebtg_config_file_path.exists():
        logger.info(f"EBTG config '{ebtg_config_file_path.name}' not found or not specified. Creating with default values at '{ebtg_config_file_path.resolve()}'.")
        temp_ebtg_cfg_manager = EbtgConfigManager(str(ebtg_config_file_path))
        default_ebtg_cfg = temp_ebtg_cfg_manager.get_default_config()
        if args.btg_config:
            default_ebtg_cfg["btg_config_path"] = str(Path(args.btg_config).resolve())
        temp_ebtg_cfg_manager.save_config(default_ebtg_cfg)
    elif args.btg_config: # If EBTG config exists but user also specified btg_config via CLI
        logger.info(f"Updating 'btg_config_path' in '{ebtg_config_file_path.name}' with CLI argument: {args.btg_config}")
        ebtg_cfg_manager = EbtgConfigManager(str(ebtg_config_file_path))
        current_ebtg_cfg = ebtg_cfg_manager.load_config()
        current_ebtg_cfg["btg_config_path"] = str(Path(args.btg_config).resolve())
        ebtg_cfg_manager.save_config(current_ebtg_cfg)

    # Ensure a default BTG config exists if pointed to by EBTG config and it's missing
    loaded_ebtg_config = EbtgConfigManager(str(ebtg_config_file_path)).load_config()
    btg_config_path_from_ebtg_cfg_str = loaded_ebtg_config.get("btg_config_path")

    if btg_config_path_from_ebtg_cfg_str:
        effective_btg_config_path = Path(btg_config_path_from_ebtg_cfg_str)
        if not effective_btg_config_path.exists():
            logger.warning(f"BTG config path '{effective_btg_config_path}' (from EBTG config) does not exist.")
            if effective_btg_config_path.parent.is_dir(): # Try to create if parent (btg_module) exists
                try:
                    from btg_module.config_manager import ConfigManager as BtgConfigManager
                    logger.info(f"Attempting to create a default BTG config at '{effective_btg_config_path}'.")
                    temp_btg_cfg_manager = BtgConfigManager(str(effective_btg_config_path))
                    temp_btg_cfg_manager.save_config(temp_btg_cfg_manager.get_default_config())
                except ImportError:
                    logger.error("Could not import BTG's ConfigManager. Ensure btg_module is accessible and in PYTHONPATH.")
                except Exception as e_btg_create:
                    logger.error(f"Error creating default BTG config: {e_btg_create}")

    try:
        logger.info(f"Initializing EbtgAppService with EBTG config: {ebtg_config_file_path.resolve()}")
        app_service = EbtgAppService(config_path=str(ebtg_config_file_path.resolve()))
        app_service.translate_epub(args.input_epub, args.output_epub)
        logger.info(f"EBTG processing finished for '{args.input_epub}'. Output: '{args.output_epub}'")
    except EbtgProcessingError as e:
        logger.error(f"EBTG Processing Error: {e}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        logger.critical(f"An unexpected critical error occurred in EBTG CLI: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()