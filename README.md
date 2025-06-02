<div contenteditable="true" translate="no" class="ProseMirror"><h2>EBTG (Epub Batch Translator with Gemini) - 아키텍처 설계 (v7 - Simplified: API 중심 XHTML 생성)</h2><p><strong>1. 개요</strong></p><p>EBTG (Epub Batch Translator with Gemini)는 기존 BTG (Batch Translator with Gemini)를 핵심 번역 엔진으로 사용하여 EPUB 파일을 번역하도록 설계된 확장 프로그램입니다. 본 아키텍처(v7)는 <strong>구현 난이도 최소화</strong>를 목표로 하며, <strong>HTML 구조 생성 및 복원 책임을 Gemini API에 최대한 위임</strong>합니다. EBTG는 EPUB에서 소설의 주요 텍스트 내용과 <code>&lt;img&gt;</code> 태그 정보를 추출하여 API에 전달하고, API는 이 정보를 바탕으로 번역된 텍스트를 포함하는 <strong>완전한 XHTML 문자열을 직접 생성</strong>합니다.</p><p><strong>2. 핵심 원칙</strong></p><ul><li><p><strong>구현 용이성 최우선:</strong> EBTG 내부의 HTML 파싱 및 재구성 로직을 최소화하여 개발 복잡도를 대폭 낮춥니다.</p></li><li><p><strong>API 중심 구조 생성:</strong> 번역된 콘텐츠를 포함하는 XHTML 구조의 생성 책임을 Gemini API의 창의적 능력과 구조화된 출력(단순 문자열 형태)에 의존합니다.</p></li><li><p><strong><code>&lt;img&gt;</code> 태그 위치 상대적 보존:</strong> API 프롬프트를 통해 원본 <code>&lt;img&gt;</code> 태그의 정보(src, alt)와 상대적인 순서가 번역된 XHTML에서도 유지되도록 요청합니다.</p></li><li><p><strong>텍스트 중심 번역:</strong> 주로 소설과 같이 텍스트 내용이 중심이 되는 EPUB에 적합한 간소화된 접근 방식입니다.</p></li><li><p><strong>모듈성 및 재사용성:</strong> BTG를 번역 요청 전달 및 API 응답 수신 창구로 활용합니다.</p></li></ul><p><strong>3. 제안된 EBTG 아키텍처 계층 및 구성 요소 (v6에서 대폭 간소화)</strong></p><pre><code>+-------------------------------------+
|   EBTG 프리젠테이션 계층            |
|   (ebtg_gui.py, ebtg_cli.py)        |  사용자 인터페이스
+-----------------+-------------------+
                  |
                  v
+-------------------------------------+
|   EBTG 서비스 계층                  |
|   (ebtg_app_service.py)             |  EPUB 번역 워크플로우 조정
+-----------------+-------------------+
                  |
                  | 사용
                  v
+-------------------------------------+
|   EBTG 비즈니스 로직 계층           |
|   ├── epub_processor_service.py     |  EPUB 파일 열기/닫기, XHTML 파일 목록화, 최종 EPUB 재조립
|   └── simplified_html_extractor.py  |  XHTML에서 순수 텍스트 블록과 &lt;img&gt; 태그 정보 순차 추출
+-----------------+-------------------+
                  | (번역 요청: 텍스트 블록 리스트 + 이미지 정보 리스트)
                  | 호출
                  v
+-------------------------------------+
|   BTG 통합 레이어                   |  EBTG와 BTG 모듈 간 인터페이스
|   (btg_integration_service.py)      |  (API 요청용 프롬프트 및 데이터 구성)
+-----------------+-------------------+
                  |
                  v
+-------------------------------------+
|   BTG 모듈 (핵심 번역기)            |
|   ├── app_service.py                |  (EBTG로부터 받은 데이터로 Gemini API 호출)
|   ├── translation_service.py        |  (GeminiClient를 통해 "XHTML 생성" 요청)
|   └── gemini_client.py              |  (구조화된 출력으로 XHTML 문자열 반환 요청)
+-------------------------------------+
                  ^ (번역 결과: Gemini API가 생성한 XHTML 문자열)
                  | epub_processor_service로 전달되어 파일 내용 교체
                  |
+-------------------------------------+
|   EBTG/BTG 인프라 계층              |
|   - EPUB 라이브러리 (EbookLib)      |
|   - HTML 파서 (BeautifulSoup - 최소한의 추출용) |
|   - BTG의 FileHandler, Logger 등    |
|   - ProgressPersistenceService      |
+-------------------------------------+

<br class="ProseMirror-trailingBreak"></code></pre><p><strong>4. 구성 요소 상세 설명 (간소화 관점)</strong></p><p><strong>4.1. EBTG 프리젠테이션 계층</strong></p><ul><li><p>(v6와 유사) 사용자는 EPUB 파일 선택, 출력 경로 지정, BTG 관련 기본 설정(API 키, 모델 등)을 수행합니다. HTML 보존 옵션 등 복잡한 설정은 최소화됩니다.</p></li></ul><p><strong>4.2. EBTG 서비스 계층</strong></p><ul><li><p><strong><code>ebtg_app_service.py</code>:</strong></p><ul><li><p>전체 EPUB 번역 워크플로우를 조정합니다.</p></li><li><p><code>EpubProcessorService</code>를 통해 XHTML 파일 목록을 가져옵니다.</p></li><li><p>각 XHTML 파일에 대해 <code>SimplifiedHtmlExtractor</code>를 호출하여 텍스트 블록과 이미지 정보를 추출합니다.</p></li><li><p>추출된 정보를 <code>BtgIntegrationService</code>를 통해 BTG 모듈로 전달하여 "번역된 XHTML 문자열 생성"을 요청합니다.</p></li><li><p>BTG로부터 생성된 XHTML 문자열을 받아 <code>EpubProcessorService</code>에 전달하여 원본 파일 내용을 교체하고 최종 EPUB을 빌드하도록 지시합니다.</p></li><li><p>오류 처리 및 <code>ProgressPersistenceService</code>를 통한 진행 상태 관리를 담당합니다.</p></li></ul></li></ul><p><strong>4.3. EBTG 비즈니스 로직 계층</strong></p><ul><li><p><strong><code>epub_processor_service.py</code>:</strong></p><ul><li><p><strong>책임:</strong></p><ul><li><p>EPUB 파일 열기, 내부 파일 구조(OPF, 스파인 등) 분석, XHTML 콘텐츠 파일 목록 및 순서 확보.</p></li><li><p>각 XHTML 파일의 원본 내용을 <code>SimplifiedHtmlExtractor</code>에 전달.</p></li><li><p>BTG로부터 반환받은 <strong>번역 및 재구성된 XHTML 문자열</strong>로 해당 원본 XHTML 파일의 내용을 완전히 교체.</p></li><li><p>모든 XHTML 파일 처리가 완료되면, 수정된 XHTML 파일들과 원본 EPUB의 다른 리소스(CSS, 이미지 원본, 폰트 등)를 사용하여 새로운 EPUB 파일을 생성. (CSS 등은 원본 그대로 사용되므로, API가 생성한 XHTML이 원본 CSS와 잘 호환되도록 프롬프트 엔지니어링이 중요할 수 있음)</p></li></ul></li></ul></li><li><p><strong><code>HtmlStructureService</code></strong></p><ul><li><p><strong>책임:</strong></p><ul><li><p><code>BeautifulSoup</code> 등을 사용하여 XHTML 콘텐츠를 최소한으로 파싱합니다.</p></li><li><p><strong>주요 목표:</strong> 문서의 순서대로 <strong>연속된 텍스트 블록</strong>과 <strong><code>&lt;img&gt;</code> 태그 정보</strong>를 추출합니다.</p></li><li><p>복잡한 HTML 구조 분석이나 태그 정보 저장/복원 로직은 수행하지 않습니다.</p></li><li><p><strong>추출 결과 예시 (리스트 형태):</strong></p><pre><code># simplified_html_extractor.py
def extract_text_and_images(xhtml_content: str) -&gt; list:
    # soup = BeautifulSoup(xhtml_content, 'html.parser')
    # content_items = []
    # for element in soup.body.find_all(True, recursive=False): # 예시: body 직계 자식 순회
    #     if element.name == 'img':
    #         content_items.append({
    #             "type": "image",
    #             "src": element.get('src'),
    #             "alt": element.get('alt', '') # alt 텍스트도 추출하여 번역 요청에 포함 가능
    #         })
    #     else: # 텍스트를 포함하는 다른 모든 블록 요소들
    #         # 최대한 많은 텍스트를 하나의 블록으로 합치거나,
    #         # &lt;p&gt;, &lt;div&gt; 등 주요 블록 단위로 텍스트 추출
    #         block_text = element.get_text(separator=' ', strip=True)
    #         if block_text:
    #             content_items.append({
    #                 "type": "text",
    #                 "content": block_text
    #             })
    # return content_items

    # 더 단순한 접근: 모든 텍스트를 하나의 큰 덩어리로 합치고, img 태그는 위치 마커와 정보만 전달
    # 또는, API가 잘 처리할 수 있도록 &lt;p&gt; 단위 텍스트와 이미지 정보 리스트로 전달
    processed_items = []
    # ... 로직 구현 ...
    # 예: [
    #   {"type": "text", "data": "첫 번째 문단 텍스트입니다."},
    #   {"type": "image", "data": {"src": "image1.jpg", "alt": "첫 번째 이미지"}},
    #   {"type": "text", "data": "이미지 다음의 문단 텍스트입니다."}
    # ]
    return processed_items

<br class="ProseMirror-trailingBreak"></code></pre></li><li><p>이 서비스는 추출된 텍스트 블록과 이미지 정보 리스트를 <code>EbtgAppService</code>에 반환합니다.</p></li></ul></li></ul></li></ul><p><strong>4.4. BTG 통합 레이어</strong></p><ul><li><p><strong><code>btg_integration_service.py</code>:</strong></p><ul><li><p><strong>책임:</strong></p><ul><li><p><code>EbtgAppService</code>로부터 텍스트 블록 및 이미지 정보 리스트와 목표 언어를 전달받습니다.</p></li><li><p>이 정보를 바탕으로 Gemini API에 전달할 <strong>프롬프트</strong>를 구성합니다. 프롬프트에는 번역 지시와 함께, 추출된 텍스트 블록들을 번역하고 이미지 정보(src, alt)를 사용하여 원래 순서대로 <code>&lt;img&gt;</code> 태그를 포함하는 <strong>완전한 XHTML 문자열을 생성</strong>해 달라는 요청이 포함됩니다.</p></li><li><p><strong>응답 스키마 정의:</strong> API가 단일 XHTML 문자열을 반환하도록 매우 단순한 스키마를 정의합니다.</p><pre><code># 예시 response_schema
response_schema = {
    "type": "OBJECT",
    "properties": {
        "translated_xhtml_content": {
            "type": "STRING",
            "description": "번역된 텍스트와 원본 이미지 정보를 포함하는 완전한 XHTML 문자열입니다. EPUB 콘텐츠로 바로 사용할 수 있어야 합니다."
        }
    },
    "required": ["translated_xhtml_content"]
}

<br class="ProseMirror-trailingBreak"></code></pre></li><li><p>구성된 프롬프트, 입력 데이터(텍스트/이미지 정보 리스트), 응답 스키마를 <code>StructuredTranslationRequest</code> DTO에 담아 BTG <code>AppService</code>로 전달합니다.</p></li><li><p>BTG로부터 <code>StructuredTranslationResponse</code> DTO (Gemini가 생성한 XHTML 문자열 포함)를 받아 <code>EbtgAppService</code>로 반환합니다.</p></li></ul></li></ul></li></ul><p><strong>4.5. BTG 모듈 (핵심 번역기)</strong></p><ul><li><p><strong>BTG <code>app_service.py</code>, <code>translation_service.py</code>, <code>gemini_client.py</code>:</strong></p><ul><li><p><code>BtgIntegrationService</code>로부터 <code>StructuredTranslationRequest</code> DTO를 받습니다.</p></li><li><p><strong>청킹 전략 수정:</strong> 입력 데이터(<code>structured_input_data</code> 내 텍스트 블록 리스트)가 매우 길 경우, API 토큰 제한을 고려하여 이 리스트를 여러 개의 작은 리스트로 나누어 각각 API 호출(동일 프롬프트 및 응답 스키마 사용)하고, 반환된 XHTML 문자열들을 순서대로 합치는 로직이 필요할 수 있습니다. 또는, 하나의 XHTML 파일 전체 내용을 하나의 요청으로 처리하는 것을 기본으로 하되, 너무 긴 파일은 <code>SimplifiedHtmlExtractor</code> 단계에서 미리 분할하는 방안도 고려합니다.</p></li><li><p><code>GeminiClient</code>는 <code>generation_config</code>에 <code>response_mime_type="application/json"</code>과 전달받은 <code>response_schema</code>를 포함하여 API를 호출합니다.</p></li><li><p>API로부터 받은 JSON 응답에서 <code>translated_xhtml_content</code> 문자열을 추출하여 반환합니다.</p></li></ul></li></ul><p><strong>4.6. EBTG/BTG 인프라 계층</strong></p><ul><li><p><strong>EPUB 라이브러리 (예: <code>EbookLib</code>):</strong> (v6와 동일) <code>EpubProcessorService</code>가 EPUB 파일의 압축 해제, 내부 파일 접근, 최종 패키징에 사용.</p></li><li><p><strong>HTML 파서 (예: <code>BeautifulSoup</code>):</strong> (v6와 유사하나 역할 축소) <code>SimplifiedHtmlExtractor</code>에서 텍스트 블록과 <code>&lt;img&gt;</code> 태그 정보를 최소한으로 추출하는 데 사용. 복잡한 DOM 조작이나 재구성에는 사용되지 않음.</p></li><li><p><strong>BTG의 <code>FileHandler</code>, <code>Logger</code> 재사용:</strong> (v6와 동일)</p></li><li><p><strong><code>ProgressPersistenceService</code>:</strong> (v6와 동일) XHTML 파일 단위로 처리 상태(성공/실패, 생성된 XHTML 경로 등)를 저장하여 작업 재개 지원.</p></li></ul><p><strong>5. 워크플로우 예시 (간소화)</strong></p><ol><li><p><strong>사용자:</strong> EPUB 파일 업로드, 출력 경로 지정, 번역 시작.</p></li><li><p><strong>EBTG <code>EbtgAppService</code>:</strong> <code>EpubProcessorService</code>를 통해 XHTML 파일 목록 가져옴.</p></li><li><p><strong>루프 (각 XHTML 파일에 대해):</strong></p><ul><li><p><strong>EBTG <code>SimplifiedHtmlExtractor</code>:</strong> 현재 XHTML 파일에서 텍스트 블록 리스트와 이미지 정보(<code>src</code>, <code>alt</code>) 리스트를 순서대로 추출.</p></li><li><p><strong>EBTG <code>BtgIntegrationService</code>:</strong> 추출된 정보와 "번역된 XHTML 생성" 지시 프롬프트, 단순 응답 스키마(<code>{"translated_xhtml_content": "string"}</code>)를 BTG 모듈에 전달.</p></li><li><p><strong>BTG 모듈:</strong> (필요시 입력 데이터 청킹 후) Gemini API에 구조화된 출력 요청. 프롬프트에는 "제공된 텍스트는 번역하고, 이미지 정보는 <code>&lt;img&gt;</code> 태그로 만들어 원래 순서대로 포함한 완전한 XHTML을 생성하라"는 내용 포함.</p></li><li><p><strong>Gemini API:</strong> 요청을 처리하여 번역된 텍스트와 <code>&lt;img&gt;</code> 태그가 포함된 <strong>하나의 XHTML 문자열</strong>을 생성하여 JSON 객체 내에 반환.</p></li><li><p><strong>BTG 모듈 -&gt; <code>BtgIntegrationService</code> -&gt; <code>EbtgAppService</code>:</strong> 생성된 XHTML 문자열 수신.</p></li><li><p><strong>EBTG <code>EpubProcessorService</code>:</strong> 수신된 XHTML 문자열로 원본 XHTML 파일의 내용을 완전히 교체.</p></li></ul></li><li><p><strong>EBTG <code>EpubProcessorService</code>:</strong> 모든 XHTML 파일 처리가 완료되면, 수정된 XHTML 파일들과 원본 리소스(CSS 등)를 사용하여 새 EPUB 파일 빌드.</p></li><li><p><strong>사용자:</strong> 번역 완료 알림 및 생성된 EPUB 파일 수신.</p></li></ol><p><strong>6. 주요 고려 사항 (v7 간소화 아키텍처)</strong></p><ul><li><p><strong>Gemini API의 XHTML 생성 능력 및 일관성:</strong></p><ul><li><p>이 아키텍처의 성패는 Gemini API가 얼마나 일관되고 정확하게, 그리고 EPUB 표준에 맞는 (또는 최소한 호환되는) XHTML을 생성하느냐에 달려있습니다. 프롬프트 엔지니어링이 매우 중요해집니다.</p></li><li><p>API가 생성하는 XHTML의 복잡도(CSS 클래스, ID, 중첩 구조 등)는 제한적일 가능성이 높으며, 원본의 정교한 레이아웃이나 스타일은 대부분 손실될 수 있습니다. <strong>"소설의 텍스트 요소"</strong> 번역에는 적합할 수 있으나, 디자인이 중요한 EPUB에는 부적합합니다.</p></li></ul></li><li><p><strong><code>&lt;img&gt;</code> 태그 위치 보장:</strong></p><ul><li><p>프롬프트를 통해 <code>&lt;img&gt;</code> 태그의 <code>src</code>와 <code>alt</code>를 사용하고, 텍스트 블록과의 상대적 순서를 유지하도록 요청해야 합니다. 하지만 API의 "창의성"으로 인해 100% 정확한 위치 보장은 어려울 수 있으며, 약간의 위치 변동이나 주변 태그 변화는 감수해야 할 수 있습니다.</p></li></ul></li><li><p><strong>번역 품질:</strong></p><ul><li><p>API가 번역과 동시에 HTML 구조 생성까지 담당하므로, 순수 텍스트 번역에만 집중할 때보다 번역의 미묘한 뉘앙스나 자연스러움이 떨어질 가능성이 있습니다. (사용자님이 이전 피드백에서 우려하셨던 부분)</p></li></ul></li><li><p><strong>CSS 및 스타일링:</strong></p><ul><li><p>API가 생성하는 XHTML은 최소한의 구조만 가질 가능성이 높습니다. 원본 EPUB의 CSS 파일이 그대로 적용되겠지만, API가 생성한 XHTML의 태그 구조가 원본과 많이 다르면 CSS가 제대로 적용되지 않아 레이아웃이 깨질 수 있습니다.</p></li></ul></li><li><p><strong>토큰 사용량 및 비용:</strong></p><ul><li><p>입력 프롬프트에 텍스트 외에 구조 생성 지시, 이미지 정보 등이 포함되고, 출력도 긴 XHTML 문자열이므로, 단순 텍스트 번역보다 토큰 사용량이 많아질 수 있습니다.</p></li></ul></li><li><p><strong>오류 처리:</strong></p><ul><li><p>API가 유효하지 않은 XHTML을 생성하거나, 특정 요청에 대해 XHTML 생성을 실패하는 경우에 대한 예외 처리가 필요합니다. 최악의 경우, 해당 XHTML 파일은 원본을 유지하거나, 텍스트만 추출하여 단순 <code>&lt;p&gt;</code> 태그로 감싸는 등의 폴백(fallback) 전략이 필요할 수 있습니다.</p></li></ul></li></ul><p><strong>7. 제안된 파일 구조 (v7 간소화)</strong></p><pre><code>EBTG_Project/
├── ebtg/
│   ├── __init__.py
│   ├── ebtg_app_service.py
│   ├── epub_processor_service.py
│   └── simplified_html_extractor.py  # HtmlStructureService 대체
│   ├── ebtg_dtos.py
│   └── ebtg_exceptions.py
│   ├── gui/ (선택적)
│   └── cli/ (선택적)
│
├── btg_integration/
│   ├── __init__.py
│   └── btg_integration_service.py    # 프롬프트 구성 및 단순 스키마 전달 역할
│
├── btg_module/
│   └── ... (BTG 프로젝트 파일, GeminiClient는 구조화된 출력(단순 문자열) 요청 기능 필요)
│
├── common/
│   └── progress_persistence_service.py
│
├── config/
│   ├── ebtg_config.json              # (설정 항목 대폭 간소화 가능)
│   └── response_schemas/             # (매우 단순한 XHTML 문자열 반환 스키마)
│       └── generate_xhtml_schema.json
│
├── main_ebtg.py
├── requirements_ebtg.txt
└── README_EBTG.md

<br class="ProseMirror-trailingBreak"></code></pre><p><strong>8. 결론</strong></p><p>v7 간소화 아키텍처는 <strong>구현 난이도를 현저히 낮추는 데 초점</strong>을 맞추고, HTML 구조 생성의 많은 부분을 Gemini API에 의존합니다. 이는 특히 텍스트 중심의 소설 EPUB 번역에는 실용적인 접근이 될 수 있지만, <strong>원본 HTML 구조의 정교한 보존이나 CSS 호환성, 그리고 API의 XHTML 생성 능력의 한계에 대해서는 명확한 기대치 관리</strong>가 필요합니다. <code>&lt;img&gt;</code> 태그의 상대적 위치 보존은 프롬프트 엔지니어링을 통해 최대한 유도해야 합니다.</p><p>이 간소화된 접근 방식이 사용자님의 목표에 더 부합하기를 바랍니다.</p></div>
