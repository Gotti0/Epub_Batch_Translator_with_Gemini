# config_manager.py
import json
from pathlib import Path
from typing import Dict, Any, Optional, Union, List 
import os # os 모듈 임포트

try:
    from .file_handler import read_json_file, write_json_file
except ImportError:
    from file_handler import read_json_file, write_json_file


DEFAULT_CONFIG_FILENAME = "config.json"

class ConfigManager:
    """
    애플리케이션 설정을 관리하는 클래스 (config.json).
    설정 파일 로드, 저장 및 기본값 제공 기능을 담당합니다.
    """
    def __init__(self, config_file_path: Optional[Union[str, Path]] = None):
        """
        ConfigManager를 초기화합니다.

        Args:
            config_file_path (Optional[Union[str, Path]], optional):
                설정 파일의 경로. None이면 기본값 'config.json'을 사용합니다.
        """
        self.config_file_path = Path(config_file_path) if config_file_path else Path(DEFAULT_CONFIG_FILENAME)

    def get_default_config(self) -> Dict[str, Any]:
        """
        애플리케이션의 기본 설정을 반환합니다.
        이 설정은 config.json 파일이 없거나 특정 키가 누락된 경우 사용될 수 있습니다.

        Returns:
            Dict[str, Any]: 기본 설정 딕셔너리.
        """
        return {
            "api_key": "",  
            "api_keys": [], 
            "service_account_file_path": None,
            "use_vertex_ai": False,
            "gcp_project": None,
            "gcp_location": None,
            "auth_credentials": "", 
            "requests_per_minute": 60, # 분당 요청 수 제한 (0 또는 None이면 제한 없음)
            "novel_language": "auto", # 로어북 추출 및 번역 출발 언어 (자동 감지)
            "novel_language_fallback": "ja", # 자동 감지 실패 시 사용할 폴백 언어
            "model_name": "gemini-2.0-flash",
            "temperature": 0.7,
            "top_p": 0.9,
            "universal_translation_prompt": ( # BTG 모듈 자체 실행 시 사용될 기본 범용 프롬프트
                "Translate the following text to {target_language}. "
                "If LOREBOOK_CONTEXT is provided, refer to it. "
                "Text to translate: {{slot}} "
                "LOREBOOK_CONTEXT: {{lorebook_context}}"
            ),
            # 콘텐츠 안전 재시도 설정
            "use_content_safety_retry": True,
            "max_content_safety_split_attempts": 3,
            "min_content_safety_chunk_size": 100,
            "content_safety_split_by_sentences": True,
            "max_workers": 4,
            "chunk_size": 6000,
            "enable_post_processing": True,
            "lorebook_extraction_temperature": 0.2, # 로어북 추출 온도

            # 로어북 관련 기본 설정 추가
            "lorebook_sampling_method": "uniform",
            "lorebook_sampling_ratio": 25.0,
            "lorebook_max_entries_per_segment": 5,
            "lorebook_max_chars_per_entry": 200,
            "lorebook_keyword_sensitivity": "medium",
            "lorebook_priority_settings": {
                "character": 5,
                "worldview": 5,
                "story_element": 5
            },
            "lorebook_chunk_size": 8000,
            "lorebook_ai_prompt_template": "First, identify the BCP-47 language code of the following text.\nThen, using that identified language as the source language for the keywords, extract major characters, places, items, important events, settings, etc., from the text.\nEach item in the 'entities' array should have 'keyword', 'description', 'category', 'importance'(1-10), 'isSpoiler'(true/false) keys.\nSummarize descriptions to not exceed {max_chars_per_entry} characters, and extract a maximum of {max_entries_per_segment} items.\nFor keyword extraction, set sensitivity to {keyword_sensitivity} and prioritize items based on: {priority_settings}.\nText: ```\n{novelText}\n```\nRespond with a single JSON object containing two keys:\n1. 'detected_language_code': The BCP-47 language code you identified (string).\n2. 'entities': The JSON array of extracted lorebook entries.\nExample response:\n{\n  \"detected_language_code\": \"ja\",\n  \"entities\": [\n    {\"keyword\": \"主人公\", \"description\": \"物語の主要なキャラクター\", \"category\": \"인물\", \"importance\": 10, \"isSpoiler\": false}\n  ]\n}\nEnsure your entire response is a single valid JSON object.",
            "lorebook_conflict_resolution_batch_size": 5,
            # 후처리 관련 설정 (기존 위치에서 이동 또는 기본값으로 통합)
            "remove_translation_headers": True,
            "remove_markdown_blocks": True,
            "remove_chunk_indexes": True,
            "clean_html_structure": True,
            "validate_html_after_processing": True,
            # "pronouns_csv": None, # 제거됨
            "lorebook_conflict_resolution_prompt_template": "다음은 동일 키워드 '{keyword}'에 대해 여러 출처에서 추출된 로어북 항목들입니다. 이 정보들을 종합하여 가장 정확하고 포괄적인 단일 로어북 항목으로 병합해주세요. 병합된 설명은 한국어로 작성하고, 카테고리, 중요도, 스포일러 여부도 결정해주세요. JSON 객체 (키: 'keyword', 'description', 'category', 'importance', 'isSpoiler') 형식으로 반환해주세요.\n\n충돌 항목들:\n{conflicting_items_text}\n\nJSON 형식으로만 응답해주세요.",
            "lorebook_output_json_filename_suffix": "_lorebook.json",

            # 동적 로어북 주입 설정
            "enable_dynamic_lorebook_injection": False, # EBTG에서는 이 설정을 직접 사용하지 않고, TranslationService가 자체 로어북을 사용.
            "xhtml_generation_max_chars_per_batch": 100000, # XHTML 생성 시 API 요청당 최대 프롬프트 문자 수 (근사치)
            "max_lorebook_entries_per_chunk_injection": 3,
            "max_lorebook_chars_per_chunk_injection": 500
        }

    def load_config(self, use_default_if_missing: bool = True) -> Dict[str, Any]:
        """
        설정 파일 (config.json)을 로드합니다.
        파일이 없거나 오류 발생 시 기본 설정을 반환할 수 있습니다.

        Args:
            use_default_if_missing (bool): 파일이 없거나 읽기 실패 시 기본 설정을 사용할지 여부.

        Returns:
            Dict[str, Any]: 로드된 설정 또는 기본 설정.
        """
        try:
            if self.config_file_path.exists():
                config_data = read_json_file(self.config_file_path)
                default_config = self.get_default_config()
                final_config = default_config.copy()
                final_config.update(config_data)

                if not final_config.get("api_keys") and final_config.get("api_key"):
                    final_config["api_keys"] = [final_config["api_key"]]
                elif final_config.get("api_keys") and not final_config.get("api_key"):
                    final_config["api_key"] = final_config["api_keys"][0] if final_config["api_keys"] else ""
                
                # max_workers 유효성 검사 및 기본값 설정
                if not isinstance(final_config.get("max_workers"), int) or final_config.get("max_workers", 0) <= 0:
                    final_config["max_workers"] = default_config["max_workers"]

                # 모든 기본 설정 키에 대해 누락된 경우 기본값으로 채우기 (update로 대부분 처리되지만, 명시적 보장)
                for key in default_config:
                    if key not in final_config:
                        final_config[key] = default_config[key]


                return final_config
            elif use_default_if_missing:
                print(f"정보: 설정 파일 '{self.config_file_path}'을(를) 찾을 수 없습니다. 기본 설정을 사용합니다.")
                return self.get_default_config()
            else:
                raise FileNotFoundError(f"설정 파일 '{self.config_file_path}'을(를) 찾을 수 없습니다.")
        except json.JSONDecodeError as e:
            print(f"오류: 설정 파일 '{self.config_file_path}' 파싱 중 오류 발생: {e}")
            if use_default_if_missing:
                print("정보: 기본 설정을 사용합니다.")
                return self.get_default_config()
            else:
                raise
        except Exception as e:
            print(f"오류: 설정 파일 '{self.config_file_path}' 로드 중 오류 발생: {e}")
            if use_default_if_missing:
                print("정보: 기본 설정을 사용합니다.")
                return self.get_default_config()
            else:
                raise

    def save_config(self, config_data: Dict[str, Any]) -> bool:
        """
        주어진 설정 데이터를 JSON 파일 (config.json)에 저장합니다.

        Args:
            config_data (Dict[str, Any]): 저장할 설정 데이터.

        Returns:
            bool: 저장 성공 시 True, 실패 시 False.
        """
        try:
            if "api_keys" in config_data and config_data["api_keys"]:
                if not config_data.get("api_key") or config_data["api_key"] != config_data["api_keys"][0]:
                    config_data["api_key"] = config_data["api_keys"][0]
            elif "api_key" in config_data and config_data["api_key"] and not config_data.get("api_keys"):
                 config_data["api_keys"] = [config_data["api_key"]]
            
            # max_workers 유효성 검사 (저장 시)
            if "max_workers" in config_data:
                try:
                    mw = int(config_data["max_workers"])
                    if mw <= 0:
                        config_data["max_workers"] = 4
                except (ValueError, TypeError):
                    config_data["max_workers"] = 4


            write_json_file(self.config_file_path, config_data, indent=4)
            print(f"정보: 설정이 '{self.config_file_path}'에 성공적으로 저장되었습니다.")
            return True
        except Exception as e:
            print(f"오류: 설정 파일 '{self.config_file_path}' 저장 중 오류 발생: {e}")
            return False

if __name__ == '__main__':
    test_output_dir = Path("test_config_manager_output")
    test_output_dir.mkdir(exist_ok=True)

    print("--- 1. 기본 설정 로드 테스트 (파일 없음) ---")
    default_config_path = test_output_dir / "default_config.json"
    if default_config_path.exists():
        default_config_path.unlink()

    manager_no_file = ConfigManager(default_config_path)
    config1 = manager_no_file.load_config()
    print(f"로드된 설정 (파일 없음): {json.dumps(config1, indent=2, ensure_ascii=False)}")
    assert config1["model_name"] == "gemini-2.0-flash"
    assert config1["api_key"] == ""
    assert config1["api_keys"] == [] 
    assert config1["service_account_file_path"] is None
    assert config1["use_vertex_ai"] is False
    assert config1["novel_language"] == "auto" # Changed from ko to auto to match new default
    assert config1["novel_language_fallback"] == "ja"
    assert config1["max_workers"] == (4) # max_workers 기본값 확인
    assert config1["requests_per_minute"] == 60 # RPM 기본값 확인
    assert config1["enable_dynamic_lorebook_injection"] is False
    assert config1["max_lorebook_entries_per_chunk_injection"] == 3
    assert config1["xhtml_generation_max_chars_per_batch"] == 100000
    assert config1["max_lorebook_chars_per_chunk_injection"] == 500

    print("\n--- 2. 설정 저장 테스트 (api_keys 및 max_workers 사용) ---")
    config_to_save = manager_no_file.get_default_config()
    config_to_save["api_keys"] = ["key1_from_list", "key2_from_list"]
    config_to_save["service_account_file_path"] = "path/to/vertex_sa.json"
    config_to_save["use_vertex_ai"] = True
    config_to_save["gcp_project"] = "test-project"
    config_to_save["model_name"] = "gemini-pro-custom"
    config_to_save["novel_language"] = "en"
    config_to_save["novel_language_fallback"] = "en_gb"
    config_to_save["max_workers"] = 4 # max_workers 값 설정
    config_to_save["requests_per_minute"] = 30 
    config_to_save["enable_dynamic_lorebook_injection"] = True
    config_to_save["lorebook_json_path"] = "path/to/active_lorebook.json" # 통합된 경로 사용 예시
    save_success = manager_no_file.save_config(config_to_save)
    print(f"설정 저장 성공 여부: {save_success}")
    assert save_success

    print("\n--- 3. 저장된 설정 로드 테스트 (api_keys 및 max_workers 확인) ---")
    manager_with_file = ConfigManager(default_config_path)
    config2 = manager_with_file.load_config()
    print(f"로드된 설정 (저장 후): {json.dumps(config2, indent=2, ensure_ascii=False)}")
    assert config2["api_keys"] == ["key1_from_list", "key2_from_list"]
    assert config2["api_key"] == "key1_from_list" 
    assert config2["service_account_file_path"] == "path/to/vertex_sa.json"
    assert config2["use_vertex_ai"] is True
    assert config2["gcp_project"] == "test-project"
    assert config2["model_name"] == "gemini-pro-custom"
    assert config2["novel_language"] == "en"
    assert config2["novel_language_fallback"] == "en_gb"
    # 로어북 기본 설정값 확인
    assert config2.get("lorebook_sampling_method") == "uniform"
    assert config2.get("lorebook_chunk_size") == 8000
    assert config2.get("lorebook_output_json_filename_suffix") == "_lorebook.json"
    assert config2["requests_per_minute"] == 30
    assert config2["max_workers"] == 4 # 저장된 max_workers 값 확인
    assert config2["enable_dynamic_lorebook_injection"] is True
    assert config2["max_lorebook_entries_per_chunk_injection"] == 3 # 기본값 유지 확인
    assert config2["lorebook_json_path"] == "path/to/active_lorebook.json" # 통합된 경로 확인

    print("\n--- 4. 부분 설정 파일 로드 테스트 (api_key만 있고 api_keys는 없는 경우) ---")
    partial_config_path_api_key_only = test_output_dir / "partial_api_key_only.json"
    partial_data_api_key_only = {
        "api_key": "single_api_key_test",
        "temperature": 0.5,
        "max_workers": "invalid", # 잘못된 max_workers 값 테스트
        "requests_per_minute": 0, # RPM 제한 없음 테스트
        "lorebook_sampling_ratio": 50.0, # 로어북 설정 중 하나만 포함
        "max_lorebook_chars_per_chunk_injection": 600 # 동적 주입 설정 중 하나만 포함
    }
    write_json_file(partial_config_path_api_key_only, partial_data_api_key_only)

    manager_partial_api_key = ConfigManager(partial_config_path_api_key_only)
    config3 = manager_partial_api_key.load_config()
    print(f"로드된 설정 (api_key만 존재, 잘못된 max_workers): {json.dumps(config3, indent=2, ensure_ascii=False)}")
    assert config3["api_key"] == "single_api_key_test"
    assert config3["api_keys"] == ["single_api_key_test"] 
    assert config3["temperature"] == 0.5
    assert config3["model_name"] == "gemini-2.0-flash"
    assert config3.get("lorebook_sampling_ratio") == 50.0 # 저장된 로어북 설정 확인
    assert config3.get("lorebook_max_entries_per_segment") == 5 # 기본 로어북 설정 확인
    assert config3["max_workers"] == (4) # 잘못된 값일 경우 기본값으로 복원되는지 확인
    assert config3["requests_per_minute"] == 0 
    assert config3["enable_dynamic_lorebook_injection"] is False # 기본값 확인
    assert config3["max_lorebook_chars_per_chunk_injection"] == 600 # 저장된 값 확인

    print("\n--- 5. 부분 설정 파일 로드 테스트 (api_keys만 있고 api_key는 없는 경우) ---")
    partial_config_path_api_keys_only = test_output_dir / "partial_api_keys_only.json"
    partial_data_api_keys_only = {
        "api_keys": ["list_key1", "list_key2"],
        "chunk_size": 7000,
        "max_workers": 0 # 0 이하의 값 테스트
    }
    write_json_file(partial_config_path_api_keys_only, partial_data_api_keys_only)

    manager_partial_api_keys = ConfigManager(partial_config_path_api_keys_only)
    config4 = manager_partial_api_keys.load_config()
    print(f"로드된 설정 (api_keys만 존재, 0 이하 max_workers): {json.dumps(config4, indent=2, ensure_ascii=False)}")
    assert config4["api_keys"] == ["list_key1", "list_key2"]
    assert config4["api_key"] == "list_key1" 
    assert config4["chunk_size"] == 7000
    assert config4["model_name"] == "gemini-2.0-flash"
    assert config4["max_workers"] == (4) # 0 이하의 값일 경우 기본값으로 복원

    print("\n테스트 완료.")
