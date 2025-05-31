# EBTG (Epub Batch Translator with Gemini)

## 1. 개요 (Overview)

EBTG (Epub Batch Translator with Gemini)는 기존 BTG (Batch Translator with Gemini)를 핵심 번역 엔진으로 사용하여 EPUB 파일을 일괄 번역하도록 설계된 확장 프로그램입니다. EBTG는 번역 품질과 자연스러움을 최우선 가치로 두며, Gemini API의 구조화된 출력 기능을 선택적이고 단계적으로 적용하여 HTML 구조 보존의 안정성을 높이는 것을 목표로 합니다.

초기 단계에서는 자연스러운 번역에 집중하고, 이후 단계에서 구조화된 출력을 활용한 2단계 파이프라인 또는 중요도가 낮은 요소에 대한 제한적 적용을 통해 번역 품질과 HTML 구조 보존 간의 균형을 맞추고자 합니다.

## 2. 핵심 원칙 (Core Principles)

*   **번역 품질 최우선:** HTML 구조의 완벽한 보존보다 번역문의 자연스러움, 정확성, 가독성을 최우선으로 합니다.
*   **구조화된 출력의 신중한 활용:** 구조화된 출력의 편리성은 인정하나, 번역 품질 저하 가능성을 인지하고, 이를 완화할 수 있는 전략(예: 2단계 파이프라인, 제한적 적용)을 사용합니다.
*   **점진적 개발 및 품질 검증:** Phase별 개발을 통해 안정성을 확보하고, 각 단계에서 번역 품질과 HTML 구조 보존 수준을 면밀히 검증합니다.
*   **모듈성 및 재사용성:** BTG를 독립 모듈로 활용하고, BTG의 기본 번역 파이프라인을 최대한 재사용합니다.
*   **계층형 아키텍처:** 관심사 분리를 통해 유지보수성과 확장성을 확보합니다.

## 3. 주요 기능 (Key Features)

*   **EPUB 파일 일괄 번역:** 여러 EPUB 파일을 한 번에 번역합니다.
*   **Gemini API 활용:** Google의 Gemini API를 핵심 번역 엔진으로 사용합니다.
*   **단계별 번역 전략 (Phased Approach):**
    *   **Phase 1 & 2:** 자연스러운 번역 품질에 집중. 순수 텍스트를 추출하여 번역 후, 원본 DOM 구조에 기반하여 텍스트 노드를 교체하는 방식으로 HTML 구조를 안정적으로 보존합니다.
        *   Phase 1: 기본적인 블록 태그(&lt;p&gt;, &lt;h1&gt;-&lt;h6&gt;, &lt;li&gt;) 내 텍스트 처리.
        *   Phase 2: 주요 인라인 태그(&lt;strong&gt;, &lt;em&gt;, &lt;a&gt;의 텍스트, &lt;img&gt;의 alt 등) 내 텍스트 처리 및 해당 태그 보존.
    *   **Phase 3:** 번역 품질과 HTML 구조 보존의 균형을 목표로 합니다.
        *   **2단계 파이프라인:** 1차로 자연스러운 번역을 수행한 후, 이 번역문과 원본 HTML 구조 정보를 바탕으로 Gemini API에 구조화된 재구성을 요청합니다.
        *   **제한적 구조화 출력:** 표나 특정 메타데이터 블록처럼 구조가 명확하고 구조화된 출력이 유리한 부분에 대해서만 직접 구조화된 출력을 사용합니다.
*   **사용자 인터페이스 (선택 사항):**
    *   GUI (Graphical User Interface) 제공 (예: Tkinter, PyQt).
    *   CLI (Command-Line Interface) 제공.
*   **설정 관리:** EBTG 특정 설정 및 BTG 모듈 설정을 관리합니다.
*   **진행 상황 관리:** 번역 작업 시작, 중지, 재개 기능 및 진행 상황 표시.
*   **EPUB 구조 분석 및 재조립:** EPUB 파일의 내부 구조(메타데이터, 콘텐츠, 리소스)를 분석하고, 번역 후 새로운 EPUB 파일로 재조립합니다.
*   **콘텐츠 분할:** XHTML 콘텐츠를 효율적인 처리 단위(예: 파일 단위, 챕터/섹션 기반)로 분할합니다.
*   **진행 상태 저장 및 복구:** 작업 중단 시 중단된 지점부터 번역을 재개할 수 있도록 지원합니다.
*   **품질 모니터링 (선택적):** 번역 품질을 자동 평가하거나 모니터링하는 기능을 포함할 수 있습니다.

## 4. 아키텍처 개요 (Architecture Overview)

EBTG는 계층형 아키텍처를 채택하여 각 구성 요소의 책임을 명확히 분리하고 유지보수성과 확장성을 높입니다.

```
+-------------------------------------+
|   EBTG 프리젠테이션 계층            |
|   (ebtg_gui.py, ebtg_cli.py)        |  사용자 인터페이스
+-----------------+-------------------+
                  |
                  v
+-------------------------------------+
|   EBTG 서비스 계층                  |
|   (ebtg_app_service.py)             |  전체 EPUB 번역 워크플로우 조정, 전략 선택
+-----------------+-------------------+
                  |
                  | 사용
                  v
+-------------------------------------+
|   EBTG 비즈니스 로직 계층           |
|   ├── epub_processor_service.py     |  EPUB 파일 레벨 처리
|   ├── content_segmentation_service.py|  XHTML 콘텐츠를 "주요 세그먼트"로 분할
|   └── html_structure_service.py     |  HTML 구조 분석, (Phase 1) 순수 텍스트 추출 및 DOM 기반 복원,
|                                     |  (Phase 3) Gemini 입력용 구조화 데이터 생성 (2단계 파이프라인용)
+-----------------+-------------------+
                  | (번역 요청: Phase 1 - 순수 텍스트 + 구조 정보 ID)
                  | (번역 요청: Phase 3 - 자연어 번역 결과 + 구조화 요청 스키마)
                  | 호출
                  v
+-------------------------------------+
|   BTG 통합 레이어                   |  EBTG와 BTG 모듈 간 인터페이스
|   (btg_integration_service.py)      |  (Phase별 다른 데이터/요청 유형 처리)
+-----------------+-------------------+
                  |
                  v
+-------------------------------------+
|   BTG 모듈 (핵심 번역기)            |  (Phase 3: 구조화된 출력 요청 기능 지원)
|   ├── app_service.py                |
|   ├── translation_service.py        |  (Phase 1: 일반 텍스트 번역, Phase 3: 2단계 구조화)
|   └── gemini_client.py              |
+-------------------------------------+
                  ^ (번역 결과: Phase 1 - 번역된 순수 텍스트)
                  ^ (번역 결과: Phase 3 - 구조화된 JSON 응답)
                  | html_structure_service로 반환되어 HTML 재구성
                  |
+-------------------------------------+
|   EBTG/BTG 인프라 계층              |
|   - EPUB 라이브러리, HTML 파서      |
|   - BTG의 FileHandler, Logger 등    |
|   - ProgressPersistenceService      |
|   - QualityMonitorService (선택적)  |  (번역 품질 자동 평가 또는 모니터링)
+-------------------------------------+
```

주요 계층은 다음과 같습니다:
*   **EBTG 프리젠테이션 계층:** 사용자 인터페이스 (GUI, CLI)를 담당합니다.
*   **EBTG 서비스 계층:** 전체 EPUB 번역 워크플로우를 조정하고, 번역 전략을 선택합니다.
*   **EBTG 비즈니스 로직 계층:** EPUB 파일 처리, 콘텐츠 분할, HTML 구조 분석 및 재구성을 담당합니다.
*   **BTG 통합 레이어:** EBTG와 BTG 모듈 간의 인터페이스 역할을 합니다.
*   **BTG 모듈:** 핵심 번역 기능을 수행하며, Phase 3에서는 구조화된 출력 요청을 지원합니다.
*   **EBTG/BTG 인프라 계층:** EPUB 라이브러리, HTML 파서, 로깅, 진행 상태 저장 등 공통 기능을 제공합니다.

## 5. 설치 (Installation)

```bash
# (설치 방법은 여기에 추가될 예정입니다)
# 예시:
# pip install -r requirements_ebtg.txt
```

## 6. 사용법 (Usage)

### 6.1. CLI (Command-Line Interface)

```bash
# (CLI 사용법은 여기에 추가될 예정입니다)
# 예시:
# python main_ebtg.py --input <epub_file_path_or_directory> --output <output_directory> --config <config_file_path> --phase <1|2|3>
```

### 6.2. GUI (Graphical User Interface)

GUI가 제공될 경우, 애플리케이션을 실행하여 파일 선택, 설정 지정, 번역 시작 등의 작업을 수행할 수 있습니다.

```bash
# (GUI 실행 방법은 여기에 추가될 예정입니다)
# 예시:
# python main_ebtg.py --gui
```

## 7. 설정 (Configuration)

EBTG의 설정은 `config/ebtg_config.json` 파일을 통해 관리됩니다. 이 파일에서 EBTG 및 BTG 관련 설정(예: 번역 Phase, Gemini API 키, 모델 설정, 구조화 응답 스키마 경로 등)을 지정할 수 있습니다.

Phase 3에서 사용될 Gemini 응답 스키마는 `config/response_schemas/` 디렉토리에 JSON 파일 형태로 저장됩니다.

## 8. 프로젝트 구조 (Project Structure)

```
EBTG_Project/
├── ebtg/                             # 기본 EBTG 애플리케이션 패키지
│   ├── __init__.py
│   ├── ebtg_app_service.py           # EPUB 번역 전체 워크플로우 조정
│   ├── epub_processor_service.py     # EPUB 파일 레벨 처리
│   ├── content_segmentation_service.py # XHTML 콘텐츠 분할
│   ├── html_structure_service.py     # HTML 구조 분석 및 재구성
│   ├── ebtg_dtos.py                  # EBTG 내부 및 BTG 연동용 DTO
│   └── ebtg_exceptions.py            # EBTG 특정 예외 클래스
│   ├── gui/                          # (선택적) GUI 관련 파일
│   │   └── ebtg_gui.py
│   └── cli/                          # (선택적) CLI 관련 파일
│       └── ebtg_cli.py
│
├── btg_integration/                  # BTG 모듈과의 연동 담당
│   ├── __init__.py
│   └── btg_integration_service.py    # BTG AppService와 통신
│
├── btg_module/                       # BTG 핵심 번역 엔진 (참조 또는 포함)
│   ├── app_service.py
│   ├── translation_service.py
│   ├── gemini_client.py
│   └── ... (기타 BTG 파일들)
│
├── common/                           # 공통 유틸리티
│   ├── __init__.py
│   └── progress_persistence_service.py # 진행 상태 저장 및 복구
│   └── quality_monitor_service.py    # (선택적) 품질 모니터링
│
├── config/                           # 설정 파일 디렉토리
│   ├── __init__.py
│   ├── ebtg_config.json              # EBTG 및 BTG 통합 설정
│   └── response_schemas/             # Gemini 응답 스키마 JSON 파일들
│       ├── phase3_basic_structure.json
│       └── phase3_table_structure.json
│
├── validation/                       # (선택적) EPUB 유효성 검증
│   ├── __init__.py
│   └── epub_validation_service.py
│
├── main_ebtg.py                      # EBTG 애플리케이션 진입점
├── requirements_ebtg.txt             # Python 종속성
└── README_EBTG.md                    # 본 파일
```

## 9. 결론 (Conclusion)

EBTG는 Gemini API를 활용하여 EPUB 파일의 고품질 번역을 목표로 합니다. 번역 품질을 최우선으로 고려하며, HTML 구조 보존을 위해 단계적이고 신중한 접근 방식을 채택합니다. 초기 단계에서는 안정적인 DOM 기반의 텍스트 내용 교체를 통해 자연스러운 번역을 추구하고, 고급 단계에서는 2단계 파이프라인 또는 제한적인 구조화된 출력을 통해 품질과 구조 보존의 균형을 찾고자 합니다.

## 10. 기여 (Contributing)

(기여 방법에 대한 안내는 추후 추가될 수 있습니다.)

## 11. 라이선스 (License)

(프로젝트 라이선스 정보는 추후 추가될 수 있습니다.)