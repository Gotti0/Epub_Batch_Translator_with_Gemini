# ebtg/ebtg_gui.py

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import logging
import threading
import queue # For thread-safe log communication
import io # For TqdmToTkinter
from pathlib import Path
import json # For JSON operations in settings

# Assuming EbtgAppService is in the same directory or package
try:
    from ebtg.ebtg_app_service import EbtgAppService
    # from .config_manager import EbtgConfigManager # Not directly used by GUI for settings editing in this version
    from ebtg.ebtg_exceptions import EbtgProcessingError
    from btg_module.exceptions import BtgApiClientException, BtgServiceException, BtgFileHandlerException, BtgBusinessLogicException # For model list update and lorebook
    from btg_module.dtos import ModelInfoDTO, LorebookExtractionProgressDTO # For model list update and lorebook
    from ebtg.ebtg_dtos import EpubProcessingProgressDTO # 진행률 표시용 DTO
except ImportError: # For running script directly for testing
    # This block allows running the GUI script directly if it's in the project root
    # and other modules are discoverable (e.g., by adding project root to PYTHONPATH)
    from ebtg_app_service import EbtgAppService
    # from config_manager import EbtgConfigManager
    from ebtg_exceptions import EbtgProcessingError
    from btg_module.exceptions import BtgApiClientException, BtgServiceException, BtgFileHandlerException, BtgBusinessLogicException
    from btg_module.dtos import ModelInfoDTO, LorebookExtractionProgressDTO 
    from ebtg_dtos import EpubProcessingProgressDTO # 진행률 표시용 DTO


# GUI Log Handler using a queue for thread-safety
class GuiLogHandler(logging.Handler):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.log_queue = queue.Queue()
        # Start polling the queue for log messages
        self.text_widget.after(100, self.poll_log_queue)

    def emit(self, record):
        # Put the formatted record into the queue
        self.log_queue.put(self.format(record))

    def poll_log_queue(self):
        # Check for and display new messages from the queue
        while True:
            try:
                record = self.log_queue.get(block=False)
            except queue.Empty:
                break
            else:
                if self.text_widget.winfo_exists():
                    self.text_widget.configure(state='normal')
                    self.text_widget.insert(tk.END, record + '\n')
                    self.text_widget.configure(state='disabled')
                    self.text_widget.see(tk.END)
        if self.text_widget.winfo_exists():
            self.text_widget.after(100, self.poll_log_queue)

# TqdmToTkinter class from batch_translator_gui.py
class TqdmToTkinter(io.StringIO):
    """
    tqdm의 출력을 Tkinter ScrolledText 위젯으로 리디렉션하기 위한 클래스입니다.
    """
    def __init__(self, widget: scrolledtext.ScrolledText):
        super().__init__()
        self.widget = widget
        self.widget.tag_config("TQDM", foreground="green") # tqdm 출력용 태그 설정

    def write(self, buf):
        def append_to_widget():
            if not self.widget.winfo_exists(): return
            current_state = self.widget.cget("state")
            self.widget.config(state=tk.NORMAL)
            self.widget.insert(tk.END, buf.strip() + '\n', "TQDM") # "TQDM" 태그 사용
            self.widget.config(state=current_state) 
            self.widget.see(tk.END)
        if self.widget.winfo_exists(): 
            self.widget.after(0, append_to_widget)

    def flush(self):
        pass

# ScrollableFrame class from batch_translator_gui.py
class ScrollableFrame:
    def __init__(self, parent, height=None):
        self.main_frame = ttk.Frame(parent)
        self.canvas = tk.Canvas(self.main_frame, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.main_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_frame = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_mouse_wheel()
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        if height:
            self.canvas.configure(height=height)

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_frame, width=event.width)

    def _bind_mouse_wheel(self):
        def _on_mousewheel(event):
            # Determine scroll direction and amount based on platform
            if event.num == 5 or event.delta < 0: # Scroll down
                self.canvas.yview_scroll(1, "units")
            elif event.num == 4 or event.delta > 0: # Scroll up
                self.canvas.yview_scroll(-1, "units")
        
        # Bind mouse wheel events directly to the canvas and the scrollable frame.
        # This is more targeted than bind_all.
        for widget_to_bind in [self.canvas, self.scrollable_frame]:
            widget_to_bind.bind("<MouseWheel>", _on_mousewheel, add="+")
            widget_to_bind.bind("<Button-4>", _on_mousewheel, add="+") # For Linux scroll up
            widget_to_bind.bind("<Button-5>", _on_mousewheel, add="+") # For Linux scroll down

        # Removed: self.main_frame.bind('<Enter>', lambda e: self.canvas.focus_set())
        # This line was likely causing the canvas to steal focus, preventing input fields from being focused.
        # Optionally, clear focus or set to another widget on <Leave> if it causes issues.
        # e.g., self.main_frame.bind('<Leave>', lambda e: self.main_frame.focus_set())

class Tooltip:
    """
    위젯 위에 마우스를 올렸을 때 툴팁 메시지를 표시하는 클래스입니다.
    """
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        if self.tooltip_window or not self.text:
            return
        tooltip_x_final: int
        tooltip_y_final: int

        # Try to get position from insert cursor
        insert_bbox = None
        try:
            # Check if widget is in a state to provide bbox and is mapped
            if self.widget.winfo_exists() and self.widget.winfo_ismapped():
                insert_bbox = self.widget.bbox("insert")
        except tk.TclError:
            # Some widgets (like Buttons, Labels) raise TclError for bbox("insert")
            pass # insert_bbox remains None

        if insert_bbox: # If bbox("insert") returned coordinates
            cursor_x_rel, cursor_y_rel, _, _ = insert_bbox
            # Position tooltip relative to the insert cursor, with original offsets
            tooltip_x_final = self.widget.winfo_rootx() + cursor_x_rel + 25
            tooltip_y_final = self.widget.winfo_rooty() + cursor_y_rel + 20
        elif event: # Fallback to mouse event coordinates if insert_bbox is None or failed
            tooltip_x_final = event.x_root + 15 # Position near mouse pointer
            tooltip_y_final = event.y_root + 10
        else: # Absolute fallback (if no event, though <Enter> binding should provide it)
            tooltip_x_final = self.widget.winfo_rootx() + 20
            tooltip_y_final = self.widget.winfo_rooty() + self.widget.winfo_height() + 5


        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_attributes("-topmost", True) # Attempt to keep tooltip on top
        tw.wm_geometry(f"+{tooltip_x_final}+{tooltip_y_final}")


        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         background="#FFFFE0", relief=tk.SOLID, borderwidth=1, # Standard tooltip color
                         font=("tahoma", "8", "normal"))
        label.pack(ipadx=1)

    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
        self.tooltip_window = None

class EbtgGui:
    def __init__(self, root_window):
        self.root = root_window
        self.root.title("EBTG - EPUB 일괄 번역기 (Gemini)")
        self.root.geometry("900x750") # Adjusted size

        self.ebtg_app_service: EbtgAppService | None = None
        self.translation_thread: threading.Thread | None = None
        self._stop_event = threading.Event() 

        # --- Main Frame ---
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Initialize EbtgAppService first to load config
        try:
            self.ebtg_app_service = EbtgAppService() # Uses default config path
            logging.getLogger(__name__).info("EBTG App Service initialized by GUI.")
        except Exception as e: # type: ignore
            # Log to console if GUI logger isn't ready
            logging.getLogger(__name__).critical(f"Failed to initialize EbtgAppService in GUI: {e}", exc_info=True)
            # Show error in a simple messagebox if root window is available
            if self.root.winfo_exists():
                messagebox.showerror("치명적 오류", f"EBTG 앱 서비스 초기화 오류: {e}\nGUI가 작동하지 않을 수 있습니다.")
            # GUI setup will proceed, but start button will be disabled if service is None

        # --- Notebook for Tabs ---
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(expand=True, fill='both')

        # --- Tab 1: EPUB Translation ---
        self.epub_translation_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(self.epub_translation_tab, text='EPUB 번역') # 이미 한국어
        self._create_epub_translation_widgets(self.epub_translation_tab)

        # --- Tab 2: Translation Settings ---
        self.settings_scroll_frame = ScrollableFrame(self.notebook) # Create ScrollableFrame instance
        self.notebook.add(self.settings_scroll_frame.main_frame, text='번역 설정')
        self._create_settings_tab_widgets(self.settings_scroll_frame.scrollable_frame) # Pass the inner frame

        # --- Tab 3: Lorebook Management ---
        self.lorebook_management_scroll_frame = ScrollableFrame(self.notebook)
        self.notebook.add(self.lorebook_management_scroll_frame.main_frame, text='로어북 관리')
        self._create_lorebook_management_widgets(self.lorebook_management_scroll_frame.scrollable_frame)

        # --- Tab 4: Execution Logs --- (순서 변경됨)
        self.log_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(self.log_tab, text='실행 로그')
        self._create_log_widgets(self.log_tab) # Pass the log_tab frame

        self.setup_logging() # Setup logging after log_text widget is created

        # self.root.update_idletasks() # This was tried before.

        if self.ebtg_app_service:
            # Defer loading settings to UI until the event loop is idle
            self.root.after(0, self._initialize_ui_with_settings)
        else:
            # Disable start button if service failed to initialize
            if hasattr(self, 'start_button'): self.start_button.config(state=tk.DISABLED)
            logging.getLogger(__name__).error("EBTG App Service가 None이므로 설정 UI가 올바르게 로드되지 않을 수 있습니다.")

    def _initialize_ui_with_settings(self):
        """Helper method to load settings and update UI, called via root.after()"""
        if not self.ebtg_app_service: # Should not happen if called from the conditional block
            return
        self._load_ebtg_settings_to_ui()
        self._update_model_list_ui() # This might show message boxes if API fails

        def set_initial_focus():
            if not self.root.winfo_exists(): # Check if root window still exists
                return
            try:
                if hasattr(self, 'input_epub_entry') and self.input_epub_entry.winfo_exists():
                    logging.getLogger(__name__).info("Attempting to set initial focus...")
                    # Forcing focus to the root window first might help the OS recognize it as active
                    self.root.focus_force() # Request window manager focus for the root window
                    
                    # Then set focus to the specific widget
                    self.input_epub_entry.focus_set()
                    
                    # Optional: Verify focus (uncomment for debugging)
                    # focused_widget = self.root.focus_get()
                    # if focused_widget == self.input_epub_entry:
                    #    logging.getLogger(__name__).info("Focus successfully set on input_epub_entry.")
                    # else:
                    #    logging.getLogger(__name__).warning(f"Focus is on {focused_widget}, not input_epub_entry.")
                else:
                    logging.getLogger(__name__).warning("input_epub_entry not available for focus setting.")
            except tk.TclError as e: # This can happen if the window is destroyed while after_idle is pending
                logging.getLogger(__name__).warning(f"TclError during initial focus setting (window might be closing): {e}")
            except Exception as e:
                logging.getLogger(__name__).error(f"Unexpected error during initial focus setting: {e}", exc_info=True)

        # Schedule set_initial_focus to run when Tkinter is idle
        self.root.after_idle(set_initial_focus)

    def _create_epub_translation_widgets(self, parent_frame):
        # --- File Selection Frame ---
        file_frame = ttk.LabelFrame(parent_frame, text="파일 선택", padding="10")
        file_frame.pack(fill=tk.X, pady=5)

        ttk.Label(file_frame, text="입력 EPUB:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.input_epub_var = tk.StringVar()
        self.input_epub_entry = ttk.Entry(file_frame, textvariable=self.input_epub_var, width=60)
        self.input_epub_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        Tooltip(self.input_epub_entry, "번역할 EPUB 파일의 경로입니다.")
        self.browse_input_btn = ttk.Button(file_frame, text="Browse...", command=self.browse_input_file)
        self.browse_input_btn.grid(row=0, column=2, padx=5, pady=5)
        Tooltip(self.browse_input_btn, "컴퓨터에서 EPUB 파일을 선택합니다.")

        ttk.Label(file_frame, text="출력 EPUB:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.output_epub_var = tk.StringVar()
        self.output_epub_entry = ttk.Entry(file_frame, textvariable=self.output_epub_var, width=60)
        self.output_epub_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
        Tooltip(self.output_epub_entry, "번역된 EPUB 파일이 저장될 경로입니다.")
        self.browse_output_btn = ttk.Button(file_frame, text="Browse...", command=self.browse_output_path)
        self.browse_output_btn.grid(row=1, column=2, padx=5, pady=5)
        Tooltip(self.browse_output_btn, "번역된 파일을 저장할 위치와 파일명을 선택합니다.")

        file_frame.columnconfigure(1, weight=1)

        # --- Controls Frame ---
        controls_frame = ttk.Frame(parent_frame, padding="10")
        controls_frame.pack(fill=tk.X, pady=5)

        self.start_button = ttk.Button(controls_frame, text="번역 시작", command=self.start_translation)
        self.start_button.pack(side=tk.LEFT, padx=5)
        Tooltip(self.start_button, "선택한 EPUB 파일의 번역을 시작합니다.")

        self.stop_button = ttk.Button(controls_frame, text="중지", command=self.request_stop_translation, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        Tooltip(self.stop_button, "진행 중인 번역 작업을 중지합니다.")
        
        # --- Progress Bar and Status ---
        progress_status_frame = ttk.Frame(parent_frame, padding="5")
        progress_status_frame.pack(fill=tk.X, pady=5)

        self.progress_bar = ttk.Progressbar(progress_status_frame, orient="horizontal", length=300, mode="determinate")
        self.progress_bar.pack(fill=tk.X, expand=True, side=tk.TOP, padx=5, pady=(0,2)) # progress_bar를 위로
        Tooltip(self.progress_bar, "번역 진행 상태를 보여줍니다.")
        
        self.status_var = tk.StringVar(value="준비됨.")
        status_label = ttk.Label(progress_status_frame, textvariable=self.status_var, anchor=tk.W)
        status_label.pack(side=tk.TOP, padx=5, fill=tk.X, expand=True, pady=(2,0)) # status_label을 아래로
        Tooltip(status_label, "현재 작업 상태 메시지를 표시합니다.")

    def _create_settings_tab_widgets(self, settings_frame):
        # This frame is the self.settings_scroll_frame.scrollable_frame
        
        # API 및 인증 설정
        api_frame = ttk.LabelFrame(settings_frame, text="API 및 인증 설정 (BTG Module)", padding="10")
        api_frame.pack(fill="x", padx=5, pady=5)
        
        self.api_keys_label = ttk.Label(api_frame, text="API 키 목록 (Gemini Developer, 한 줄에 하나씩):")
        self.api_keys_label.grid(row=0, column=0, padx=5, pady=5, sticky="nw")
        self.api_keys_text = scrolledtext.ScrolledText(api_frame, width=58, height=3, wrap=tk.WORD)
        Tooltip(self.api_keys_text, "Google AI Studio에서 발급받은 Gemini API 키를 입력합니다.\n여러 개 입력 시 한 줄에 하나씩 입력하세요.")
        self.api_keys_text.grid(row=0, column=1, columnspan=2, padx=5, pady=5, sticky="ew")

        self.use_vertex_ai_var = tk.BooleanVar() # type: ignore
        self.use_vertex_ai_check = ttk.Checkbutton(api_frame, text="Vertex AI 사용 (BTG Module)", variable=self.use_vertex_ai_var, command=self._toggle_vertex_fields)
        self.use_vertex_ai_check.grid(row=1, column=0, columnspan=3, padx=5, pady=2, sticky="w")
        Tooltip(self.use_vertex_ai_check, "Google Cloud Vertex AI를 사용하여 번역하려면 선택하세요.\n선택 시 아래 Vertex AI 관련 설정을 입력해야 합니다.")

        self.service_account_file_label = ttk.Label(api_frame, text="서비스 계정 JSON 파일 (Vertex AI):")
        self.service_account_file_label.grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.service_account_file_entry = ttk.Entry(api_frame, width=50)
        self.service_account_file_entry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        Tooltip(self.service_account_file_entry, "Vertex AI 사용 시 필요한 서비스 계정 키 JSON 파일의 경로입니다.")
        self.browse_sa_file_button = ttk.Button(api_frame, text="찾아보기", command=self._browse_service_account_file)
        self.browse_sa_file_button.grid(row=2, column=2, padx=5, pady=5)
        Tooltip(self.browse_sa_file_button, "서비스 계정 JSON 파일을 선택합니다.")

        self.gcp_project_label = ttk.Label(api_frame, text="GCP 프로젝트 ID (Vertex AI):")
        self.gcp_project_label.grid(row=3, column=0, padx=5, pady=5, sticky="w")
        self.gcp_project_entry = ttk.Entry(api_frame, width=30)
        self.gcp_project_entry.grid(row=3, column=1, padx=5, pady=5, sticky="ew")
        Tooltip(self.gcp_project_entry, "Vertex AI를 사용하는 Google Cloud Platform 프로젝트의 ID입니다.")

        self.gcp_location_label = ttk.Label(api_frame, text="GCP 위치 (Vertex AI):")
        self.gcp_location_label.grid(row=4, column=0, padx=5, pady=5, sticky="w")
        self.gcp_location_entry = ttk.Entry(api_frame, width=30)
        self.gcp_location_entry.grid(row=4, column=1, padx=5, pady=5, sticky="ew")
        Tooltip(self.gcp_location_entry, "Vertex AI 서비스가 위치한 GCP 리전입니다. (예: us-central1)")

        ttk.Label(api_frame, text="모델 이름 (BTG Module):").grid(row=5, column=0, padx=5, pady=5, sticky="w")
        self.model_name_combobox = ttk.Combobox(api_frame, width=57)
        self.model_name_combobox.grid(row=5, column=1, padx=5, pady=5, sticky="ew")
        Tooltip(self.model_name_combobox, "번역에 사용할 Gemini 모델을 선택합니다.\n새로고침 버튼으로 사용 가능한 모델 목록을 업데이트할 수 있습니다.")
        self.refresh_models_button = ttk.Button(api_frame, text="새로고침", command=self._update_model_list_ui)
        self.refresh_models_button.grid(row=5, column=2, padx=5, pady=5)
        Tooltip(self.refresh_models_button, "사용 가능한 Gemini 모델 목록을 새로고침합니다.")

        # 생성 파라미터
        gen_param_frame = ttk.LabelFrame(settings_frame, text="생성 파라미터 (BTG Module)", padding="10")
        gen_param_frame.pack(fill="x", padx=5, pady=5)
        
        ttk.Label(gen_param_frame, text="Temperature:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.temperature_scale = ttk.Scale(gen_param_frame, from_=0.0, to=2.0, orient="horizontal", length=200, command=lambda v: self.temperature_label.config(text=f"{float(v):.2f}"))
        Tooltip(self.temperature_scale, "모델 응답의 무작위성을 조절합니다.\n낮을수록 결정적, 높을수록 다양성이 증가합니다. (기본값: 0.7)")
        self.temperature_scale.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.temperature_label = ttk.Label(gen_param_frame, text="0.00")
        self.temperature_label.grid(row=0, column=2, padx=5, pady=5)
        
        ttk.Label(gen_param_frame, text="Top P:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.top_p_scale = ttk.Scale(gen_param_frame, from_=0.0, to=1.0, orient="horizontal", length=200, command=lambda v: self.top_p_label.config(text=f"{float(v):.2f}"))
        Tooltip(self.top_p_scale, "모델이 다음 단어를 선택할 때 고려하는 확률 분포의 누적값을 조절합니다.\n낮을수록 보수적, 높을수록 다양한 단어 선택 (기본값: 0.9)")
        self.top_p_scale.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        self.top_p_label = ttk.Label(gen_param_frame, text="0.00")
        self.top_p_label.grid(row=1, column=2, padx=5, pady=5)

        # 파일 및 처리 설정
        processing_frame = ttk.LabelFrame(settings_frame, text="처리 설정 (BTG Module)", padding="10")
        processing_frame.pack(fill="x", padx=5, pady=5)

        ttk.Label(processing_frame, text="청크 크기 (BTG):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.btg_chunk_size_entry = ttk.Entry(processing_frame, width=10)
        Tooltip(self.btg_chunk_size_entry, "BTG 모듈 내부에서 텍스트를 나누어 API에 요청할 때의 최대 글자 수입니다. (기본값: 6000)")
        self.btg_chunk_size_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        
        ttk.Label(processing_frame, text="최대 작업자 수 (BTG):").grid(row=0, column=2, padx=5, pady=5, sticky="w")
        self.btg_max_workers_entry = ttk.Entry(processing_frame, width=5)
        self.btg_max_workers_entry.grid(row=0, column=3, padx=5, pady=5, sticky="w")
        
        ttk.Label(processing_frame, text="분당 요청 수 (RPM, BTG):").grid(row=0, column=4, padx=5, pady=5, sticky="w")
        self.btg_rpm_entry = ttk.Entry(processing_frame, width=5)
        Tooltip(self.btg_rpm_entry, "API에 분당 보낼 수 있는 최대 요청 횟수입니다. API 제한에 맞춰 조절하세요. (기본값: 60)")
        self.btg_rpm_entry.grid(row=0, column=5, padx=5, pady=5, sticky="w")

        # EBTG 자체 설정 (예: XHTML 분할 크기)
        ebtg_specific_frame = ttk.LabelFrame(settings_frame, text="EBTG 처리 설정", padding="10")
        ebtg_specific_frame.pack(fill="x", padx=5, pady=5)
        ttk.Label(ebtg_specific_frame, text="XHTML 세그먼트 목표 문자 수:").grid(row=0, column=0, padx=5, pady=5, sticky="w") # 레이블 변경
        self.ebtg_xhtml_segment_target_chars_entry = ttk.Entry(ebtg_specific_frame, width=10) # 변수명 변경
        Tooltip(self.ebtg_xhtml_segment_target_chars_entry, "하나의 XHTML 파일을 여러 조각으로 나누어 번역할 때, 각 조각의 목표 글자 수입니다.\n0 또는 음수이면 나누지 않습니다. (기본값: 4000)")
        self.ebtg_xhtml_segment_target_chars_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.ebtg_xhtml_segment_target_chars_entry.insert(0, "4000") # 기본값 변경

        # 언어 설정 (BTG Module)
        language_settings_frame = ttk.LabelFrame(settings_frame, text="언어 설정 (BTG Module)", padding="10")
        language_settings_frame.pack(fill="x", padx=5, pady=5)
        ttk.Label(language_settings_frame, text="번역 출발 언어 (BTG):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.btg_novel_language_entry = ttk.Entry(language_settings_frame, width=10)
        Tooltip(self.btg_novel_language_entry, "BTG 모듈이 텍스트 번역 시 원본 언어를 감지하지 못할 경우 사용할 언어 코드입니다.\n(예: en, ja, ko, 'auto'로 설정 시 자동 감지 시도)")
        self.btg_novel_language_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(language_settings_frame, text="폴백 언어 (BTG):").grid(row=0, column=2, padx=5, pady=5, sticky="w")
        self.btg_novel_language_fallback_entry = ttk.Entry(language_settings_frame, width=10)
        Tooltip(self.btg_novel_language_fallback_entry, "BTG 모듈이 자동 언어 감지에 실패했을 때 기본으로 사용할 언어 코드입니다. (예: ja)")
        self.btg_novel_language_fallback_entry.grid(row=0, column=3, padx=5, pady=5, sticky="w")

        # 번역 프롬프트 (EBTG - XHTML 생성용, BTG - 일반 텍스트 번역용)
        prompt_frame = ttk.LabelFrame(settings_frame, text="번역 프롬프트", padding="10")
        prompt_frame.pack(fill="both", expand=True, padx=5, pady=5)

        ttk.Label(prompt_frame, text="범용 번역 프롬프트 (EBTG & BTG):").pack(anchor=tk.W)
        self.universal_translation_prompt_text = scrolledtext.ScrolledText(prompt_frame, wrap=tk.WORD, height=10, width=70)
        Tooltip(self.universal_translation_prompt_text, "XHTML 및 일반 텍스트 번역 모두에 사용될 범용 프롬프트입니다.\n{target_language}, {{content_items}}, {{lorebook_context}}, {{slot}} 등의 플레이스홀더를 사용할 수 있습니다.")
        self.universal_translation_prompt_text.pack(fill="both", expand=True, padx=5, pady=2)


        # 콘텐츠 안전 재시도 설정 (BTG Module)
        content_safety_frame = ttk.LabelFrame(settings_frame, text="콘텐츠 안전 재시도 (BTG Module)", padding="10")
        content_safety_frame.pack(fill="x", padx=5, pady=5)
        self.btg_use_content_safety_retry_var = tk.BooleanVar()
        self.btg_use_content_safety_retry_check = ttk.Checkbutton(content_safety_frame, text="검열 오류시 청크 분할 재시도 사용", variable=self.btg_use_content_safety_retry_var)
        Tooltip(self.btg_use_content_safety_retry_check, "API가 콘텐츠 안전 문제로 응답을 거부할 경우, 텍스트를 더 작게 나누어 재시도할지 여부입니다.")
        self.btg_use_content_safety_retry_check.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(content_safety_frame, text="최대 분할 시도:").grid(row=1, column=0, sticky="w")
        self.btg_max_split_attempts_entry = ttk.Entry(content_safety_frame, width=5)
        Tooltip(self.btg_max_split_attempts_entry, "콘텐츠 안전 문제 발생 시, 텍스트를 나누어 재시도할 최대 횟수입니다. (기본값: 3)")
        self.btg_max_split_attempts_entry.grid(row=1, column=1, sticky="w")
        ttk.Label(content_safety_frame, text="최소 청크 크기:").grid(row=2, column=0, sticky="w")
        self.btg_min_chunk_size_entry = ttk.Entry(content_safety_frame, width=10)
        Tooltip(self.btg_min_chunk_size_entry, "콘텐츠 안전 문제로 텍스트를 나눌 때, 허용되는 최소 글자 수입니다. (기본값: 100)")
        self.btg_min_chunk_size_entry.grid(row=2, column=1, sticky="w")

        # 동적 로어북 주입 설정 (BTG Module)
        dyn_lorebook_frame = ttk.LabelFrame(settings_frame, text="동적 로어북 주입 (BTG Module)", padding="10")
        dyn_lorebook_frame.pack(fill="x", padx=5, pady=5)
        self.btg_enable_dynamic_lorebook_var = tk.BooleanVar()
        self.btg_enable_dynamic_lorebook_check = ttk.Checkbutton(dyn_lorebook_frame, text="동적 로어북 주입 활성화", variable=self.btg_enable_dynamic_lorebook_var)
        Tooltip(self.btg_enable_dynamic_lorebook_check, "번역 시 로어북(용어집)의 내용을 동적으로 프롬프트에 주입할지 여부입니다.")
        self.btg_enable_dynamic_lorebook_check.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(dyn_lorebook_frame, text="청크당 최대 주입 항목 수:").grid(row=1, column=0, sticky="w")
        self.btg_max_lorebook_entries_injection_entry = ttk.Entry(dyn_lorebook_frame, width=5)
        Tooltip(self.btg_max_lorebook_entries_injection_entry, "하나의 번역 요청(청크)에 주입될 로어북 항목의 최대 개수입니다. (기본값: 3)")
        self.btg_max_lorebook_entries_injection_entry.grid(row=1, column=1, sticky="w")
        ttk.Label(dyn_lorebook_frame, text="청크당 최대 주입 문자 수:").grid(row=2, column=0, sticky="w")
        self.btg_max_lorebook_chars_injection_entry = ttk.Entry(dyn_lorebook_frame, width=10)
        Tooltip(self.btg_max_lorebook_chars_injection_entry, "하나의 번역 요청(청크)에 주입될 로어북 내용의 최대 글자 수입니다. (기본값: 500)")
        self.btg_max_lorebook_chars_injection_entry.grid(row=2, column=1, sticky="w")

        # 설정 저장/로드 버튼
        action_frame = ttk.Frame(settings_frame, padding="10")
        action_frame.pack(fill="x", padx=5, pady=10) # type: ignore
        self.save_settings_button = ttk.Button(action_frame, text="EBTG 설정 저장", command=self._save_ebtg_settings) # type: ignore
        Tooltip(self.save_settings_button, "현재 탭의 모든 설정을 EBTG 설정 파일(ebtg_config.json)에 저장합니다.")
        self.save_settings_button.pack(side="left", padx=5)
        self.load_settings_button = ttk.Button(action_frame, text="EBTG 설정 불러오기", command=self._load_ebtg_settings_to_ui) # type: ignore
        Tooltip(self.load_settings_button, "EBTG 설정 파일(ebtg_config.json)에서 설정을 불러와 현재 UI에 적용합니다.")
        self.load_settings_button.pack(side="left", padx=5)

        self._toggle_vertex_fields() # Initial state
        Tooltip(settings_frame, "번역 작업과 관련된 다양한 설정을 변경합니다.\nEBTG 자체 설정과 내부적으로 사용되는 BTG 모듈의 설정을 포함합니다.")

    def _create_lorebook_management_widgets(self, parent_frame):
        # 로어북 JSON 파일 설정
        path_frame = ttk.LabelFrame(parent_frame, text="로어북 JSON 파일 (BTG Module)", padding="10")
        path_frame.pack(fill="x", padx=5, pady=5)

        ttk.Label(path_frame, text="JSON 파일 경로:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.btg_lorebook_json_path_entry = ttk.Entry(path_frame, width=50)
        self.btg_lorebook_json_path_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        Tooltip(self.btg_lorebook_json_path_entry, "BTG 모듈이 사용할 로어북(용어집) JSON 파일의 경로입니다.\n동적 로어북 주입 또는 로어북 기반 번역에 사용됩니다.")
        self.btg_browse_lorebook_json_button = ttk.Button(path_frame, text="찾아보기", command=self._browse_btg_lorebook_json_file)
        self.btg_browse_lorebook_json_button.grid(row=0, column=2, padx=5, pady=5)
        Tooltip(self.btg_browse_lorebook_json_button, "로어북 JSON 파일을 선택합니다.")

        extract_button = ttk.Button(path_frame, text="현재 EPUB에서 로어북 추출 (BTG Module)", command=self._extract_lorebook_from_epub_thread)
        extract_button.grid(row=1, column=0, columnspan=3, padx=5, pady=10)
        Tooltip(extract_button, "'EPUB 번역' 탭에서 선택된 입력 EPUB 파일의 내용을 기반으로 로어북을 자동으로 추출합니다.\n추출된 로어북은 아래에 표시되며, 지정된 경로에 저장됩니다.")

        self.btg_lorebook_progress_label = ttk.Label(path_frame, text="로어북 추출 대기 중...")
        Tooltip(self.btg_lorebook_progress_label, "로어북 추출 작업의 진행 상태를 표시합니다.")
        self.btg_lorebook_progress_label.grid(row=2, column=0, columnspan=3, padx=5, pady=2)

        # 로어북 추출 설정 프레임
        extraction_settings_frame = ttk.LabelFrame(parent_frame, text="로어북 추출 설정 (BTG Module)", padding="10")
        extraction_settings_frame.pack(fill="x", padx=5, pady=5)

        ttk.Label(extraction_settings_frame, text="샘플링 비율 (%):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        sample_ratio_frame = ttk.Frame(extraction_settings_frame)
        sample_ratio_frame.grid(row=0, column=1, columnspan=2, padx=5, pady=5, sticky="ew")
        self.btg_sample_ratio_scale = ttk.Scale(sample_ratio_frame, from_=5.0, to=100.0, orient="horizontal", length=200, command=lambda v: self.btg_sample_ratio_label.config(text=f"{float(v):.1f}%"))
        Tooltip(self.btg_sample_ratio_scale, "로어북 추출 시 원본 텍스트에서 샘플링할 비율입니다.\n100%면 전체 텍스트를 사용합니다. (기본값: 25.0%)")
        self.btg_sample_ratio_scale.pack(side="left", padx=(0,10))
        self.btg_sample_ratio_label = ttk.Label(sample_ratio_frame, text="25.0%", width=8)
        self.btg_sample_ratio_label.pack(side="left")

        ttk.Label(extraction_settings_frame, text="세그먼트 당 최대 항목 수:").grid(row=1, column=0, padx=5, pady=(15,5), sticky="w")
        self.btg_max_entries_per_segment_spinbox = ttk.Spinbox(extraction_settings_frame, from_=1, to=20, width=8)
        Tooltip(self.btg_max_entries_per_segment_spinbox, "로어북 추출 시, API에 한 번에 요청할 텍스트 조각(세그먼트)에서 추출할 최대 항목 수입니다. (기본값: 5)")
        self.btg_max_entries_per_segment_spinbox.grid(row=1, column=1, padx=5, pady=(15,5), sticky="w")
        self.btg_max_entries_per_segment_spinbox.set("5")

        ttk.Label(extraction_settings_frame, text="추출 온도:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.btg_extraction_temp_scale = ttk.Scale(extraction_settings_frame, from_=0.0, to=1.0, orient="horizontal", length=150, command=lambda v: self.btg_extraction_temp_label.config(text=f"{float(v):.2f}"))
        Tooltip(self.btg_extraction_temp_scale, "로어북 항목 추출 시 모델 응답의 무작위성입니다. 낮을수록 일관된 항목 추출. (기본값: 0.2)")
        self.btg_extraction_temp_scale.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        self.btg_extraction_temp_label = ttk.Label(extraction_settings_frame, text="0.20", width=6)
        self.btg_extraction_temp_label.grid(row=2, column=2, padx=5, pady=5)
        
        # Additional Lorebook settings from BTG GUI
        ttk.Label(extraction_settings_frame, text="샘플링 방식:").grid(row=3, column=0, padx=5, pady=5, sticky="w")
        self.btg_lorebook_sampling_method_combobox = ttk.Combobox(extraction_settings_frame, values=["uniform", "random"], width=15)
        Tooltip(self.btg_lorebook_sampling_method_combobox, "로어북 추출을 위해 원본 텍스트에서 내용을 샘플링하는 방식입니다.\nuniform: 균일 간격, random: 무작위 (기본값: uniform)")
        self.btg_lorebook_sampling_method_combobox.grid(row=3, column=1, padx=5, pady=5, sticky="w")
        self.btg_lorebook_sampling_method_combobox.set("uniform")

        ttk.Label(extraction_settings_frame, text="항목 당 최대 글자 수:").grid(row=4, column=0, padx=5, pady=5, sticky="w")
        self.btg_lorebook_max_chars_entry = ttk.Entry(extraction_settings_frame, width=10)
        Tooltip(self.btg_lorebook_max_chars_entry, "추출된 각 로어북 항목(용어 및 설명)의 최대 글자 수입니다. (기본값: 200)")
        self.btg_lorebook_max_chars_entry.grid(row=4, column=1, padx=5, pady=5, sticky="w")
        self.btg_lorebook_max_chars_entry.insert(0, "200")

        ttk.Label(extraction_settings_frame, text="키워드 민감도:").grid(row=5, column=0, padx=5, pady=5, sticky="w")
        self.btg_lorebook_keyword_sensitivity_combobox = ttk.Combobox(extraction_settings_frame, values=["low", "medium", "high"], width=15)
        Tooltip(self.btg_lorebook_keyword_sensitivity_combobox, "로어북 항목 추출 시 키워드(등장인물, 지명 등)를 얼마나 민감하게 감지할지 설정합니다. (기본값: medium)")
        self.btg_lorebook_keyword_sensitivity_combobox.grid(row=5, column=1, padx=5, pady=5, sticky="w")
        self.btg_lorebook_keyword_sensitivity_combobox.set("medium")

        ttk.Label(extraction_settings_frame, text="로어북 세그먼트 크기:").grid(row=6, column=0, padx=5, pady=5, sticky="w")
        self.btg_lorebook_chunk_size_entry = ttk.Entry(extraction_settings_frame, width=10)
        Tooltip(self.btg_lorebook_chunk_size_entry, "로어북 추출을 위해 API에 한 번에 전달하는 텍스트의 최대 글자 수입니다. (기본값: 8000)")
        self.btg_lorebook_chunk_size_entry.grid(row=6, column=1, padx=5, pady=5, sticky="w")
        self.btg_lorebook_chunk_size_entry.insert(0, "8000")

        ttk.Label(extraction_settings_frame, text="우선순위 설정 (JSON):").grid(row=7, column=0, padx=5, pady=5, sticky="nw")
        self.btg_lorebook_priority_text = scrolledtext.ScrolledText(extraction_settings_frame, width=40, height=3, wrap=tk.WORD)
        Tooltip(self.btg_lorebook_priority_text, "로어북 항목 유형별 우선순위를 JSON 형식으로 설정합니다.\n높은 숫자일수록 우선순위가 높습니다. (예: {\"character\": 5, \"worldview\": 3})")
        self.btg_lorebook_priority_text.grid(row=7, column=1, columnspan=2, padx=5, pady=5, sticky="ew")
        self.btg_lorebook_priority_text.insert('1.0', json.dumps({"character": 5, "worldview": 5, "story_element": 5}, indent=2))
        Tooltip(extraction_settings_frame, "EPUB에서 로어북(용어집)을 추출할 때 사용되는 상세 설정입니다.")

        # 동적 로어북 주입 설정 (BTG Module - 로어북 관리 탭으로 이동)
        dyn_lorebook_frame_in_lorebook_tab = ttk.LabelFrame(parent_frame, text="동적 로어북 주입 설정 (BTG Module)", padding="10")
        dyn_lorebook_frame_in_lorebook_tab.pack(fill="x", padx=5, pady=5)
        self.btg_dyn_lb_enable_var_loretab = tk.BooleanVar() # Use distinct var name
        self.btg_dyn_lb_enable_check_loretab = ttk.Checkbutton(dyn_lorebook_frame_in_lorebook_tab, text="동적 로어북 주입 활성화", variable=self.btg_dyn_lb_enable_var_loretab)
        Tooltip(self.btg_dyn_lb_enable_check_loretab, "번역 시 로어북(용어집)의 내용을 동적으로 프롬프트에 주입할지 여부입니다.\n이 설정은 '번역 설정' 탭의 동일한 설정과 연동됩니다.")
        self.btg_dyn_lb_enable_check_loretab.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(dyn_lorebook_frame_in_lorebook_tab, text="청크당 최대 주입 항목 수:").grid(row=1, column=0, sticky="w")
        self.btg_dyn_lb_max_entries_entry_loretab = ttk.Entry(dyn_lorebook_frame_in_lorebook_tab, width=5)
        Tooltip(self.btg_dyn_lb_max_entries_entry_loretab, "하나의 번역 요청(청크)에 주입될 로어북 항목의 최대 개수입니다. (기본값: 3)\n'번역 설정' 탭과 연동됩니다.")
        self.btg_dyn_lb_max_entries_entry_loretab.grid(row=1, column=1, sticky="w")
        ttk.Label(dyn_lorebook_frame_in_lorebook_tab, text="청크당 최대 주입 문자 수:").grid(row=2, column=0, sticky="w")
        self.btg_dyn_lb_max_chars_entry_loretab = ttk.Entry(dyn_lorebook_frame_in_lorebook_tab, width=10)
        Tooltip(self.btg_dyn_lb_max_chars_entry_loretab, "하나의 번역 요청(청크)에 주입될 로어북 내용의 최대 글자 수입니다. (기본값: 500)\n'번역 설정' 탭과 연동됩니다.")
        self.btg_dyn_lb_max_chars_entry_loretab.grid(row=2, column=1, sticky="w")
        Tooltip(dyn_lorebook_frame_in_lorebook_tab, "번역 시 로어북 내용을 프롬프트에 동적으로 포함시키는 것에 대한 설정입니다.")

        # 로어북 표시/관리
        lorebook_display_frame = ttk.LabelFrame(parent_frame, text="추출된 로어북 (JSON)", padding="10")
        lorebook_display_frame.pack(fill="both", expand=True, padx=5, pady=5)
        self.btg_lorebook_display_text = scrolledtext.ScrolledText(lorebook_display_frame, wrap=tk.WORD, height=10, width=70)
        self.btg_lorebook_display_text.pack(fill="both", expand=True, padx=5, pady=5)

        lorebook_display_buttons_frame = ttk.Frame(lorebook_display_frame)
        lorebook_display_buttons_frame.pack(fill="x", pady=5)
        self.btg_load_lorebook_button = ttk.Button(lorebook_display_buttons_frame, text="로어북 불러오기", command=self._load_btg_lorebook_to_display)
        Tooltip(self.btg_load_lorebook_button, "컴퓨터에 저장된 로어북 JSON 파일을 불러와 아래 텍스트 영역에 표시합니다.")
        self.btg_load_lorebook_button.pack(side="left", padx=5)
        self.btg_copy_lorebook_button = ttk.Button(lorebook_display_buttons_frame, text="JSON 복사", command=self._copy_btg_lorebook_json)
        Tooltip(self.btg_copy_lorebook_button, "아래 텍스트 영역에 표시된 로어북 JSON 내용을 클립보드에 복사합니다.")
        self.btg_copy_lorebook_button.pack(side="left", padx=5)
        self.btg_save_displayed_lorebook_button = ttk.Button(lorebook_display_buttons_frame, text="JSON 저장", command=self._save_displayed_btg_lorebook_json)
        Tooltip(self.btg_save_displayed_lorebook_button, "아래 텍스트 영역에 표시된 로어북 JSON 내용을 새 파일로 저장합니다.")
        self.btg_save_displayed_lorebook_button.pack(side="left", padx=5)
        Tooltip(lorebook_display_frame, "추출되거나 불러온 로어북의 내용을 JSON 형식으로 보여줍니다.\n여기서 직접 편집은 불가능하며, 편집 후 저장하려면 외부 편집기를 사용하세요.")

        # 로어북 설정 저장/초기화 버튼 (EBTG 설정 파일에 BTG 로어북 관련 설정을 저장)
        lorebook_action_frame = ttk.Frame(parent_frame, padding="10")
        lorebook_action_frame.pack(fill="x", padx=5, pady=5)
        self.save_btg_lorebook_settings_button = ttk.Button(lorebook_action_frame, text="로어북 관련 설정 저장 (EBTG Config)", command=self._save_ebtg_settings) # Saves all settings including these
        Tooltip(self.save_btg_lorebook_settings_button, "이 탭의 로어북 추출 및 주입 관련 설정을 포함한 모든 EBTG 설정을 저장합니다.\n('번역 설정' 탭의 저장 버튼과 동일 기능)")
        self.save_btg_lorebook_settings_button.pack(side="left", padx=5)
        # Preview and Reset might need more specific logic if they only affect BTG part of config
        # For now, they can be placeholders or trigger full EBTG config reset/preview if simpler.
        # self.reset_btg_lorebook_settings_button = ttk.Button(lorebook_action_frame, text="로어북 설정 초기화", command=self._reset_btg_lorebook_settings_in_ebtg_config)
        # self.reset_btg_lorebook_settings_button.pack(side="left", padx=5)
        # self.preview_btg_lorebook_settings_button = ttk.Button(lorebook_action_frame, text="설정 미리보기", command=self._preview_btg_lorebook_settings)
        # self.preview_btg_lorebook_settings_button.pack(side="right", padx=5)
        Tooltip(parent_frame, "EPUB에서 용어집(로어북)을 추출하고 관리하는 기능입니다.\n추출된 로어북은 번역 품질 향상에 사용될 수 있습니다.")

    def _create_log_widgets(self, parent_frame):
        self.log_text = scrolledtext.ScrolledText(parent_frame, wrap=tk.WORD, state=tk.DISABLED, height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def setup_logging(self):
        gui_handler = GuiLogHandler(self.log_text)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
        gui_handler.setFormatter(formatter)
        
        # Add handler to the root logger to capture logs from all modules.
        logging.getLogger().addHandler(gui_handler)
        logging.getLogger().setLevel(logging.INFO) # Capture INFO and above for GUI
        # Set specific levels for EBTG/BTG loggers if they are too verbose for INFO
        logging.getLogger("ebtg").setLevel(logging.DEBUG) 
        logging.getLogger("btg_module").setLevel(logging.DEBUG)

        logging.getLogger(__name__).info("GUI logging initialized.")

    def browse_input_file(self):
        filepath = filedialog.askopenfilename(
            title="입력 EPUB 파일 선택",
            filetypes=(("EPUB files", "*.epub"), ("All files", "*.*"))
        )
        if filepath:
            self.input_epub_var.set(filepath)
            p = Path(filepath)
            suggested_output = p.parent / f"{p.stem}_번역됨.epub"
            self.output_epub_var.set(str(suggested_output))

    def browse_output_path(self):
        filepath = filedialog.asksaveasfilename(
            title="Select Output EPUB File Path",
            defaultextension=".epub",
            filetypes=(("EPUB files", "*.epub"), ("All files", "*.*"))
        )
        if filepath:
            self.output_epub_var.set(filepath)

    def _browse_btg_lorebook_json_file(self):
        filepath = filedialog.askopenfilename(title="로어북 JSON 파일 선택 (BTG 모듈)", filetypes=(("JSON 파일", "*.json"), ("모든 파일", "*.*")))
        if filepath:
            self.btg_lorebook_json_path_entry.delete(0, tk.END)
            self.btg_lorebook_json_path_entry.insert(0, filepath)


    def _browse_service_account_file(self):
        filepath = filedialog.askopenfilename(title="서비스 계정 JSON 파일 선택", filetypes=(("JSON 파일", "*.json"), ("모든 파일", "*.*")))
        if filepath:
            self.service_account_file_entry.delete(0, tk.END)
            self.service_account_file_entry.insert(0, filepath)

    def _toggle_vertex_fields(self):
        use_vertex = self.use_vertex_ai_var.get()
        api_related_state = tk.DISABLED if use_vertex else tk.NORMAL
        vertex_related_state = tk.NORMAL if use_vertex else tk.DISABLED

        if hasattr(self, 'api_keys_label'): self.api_keys_label.config(state=api_related_state)
        if hasattr(self, 'api_keys_text'): self.api_keys_text.config(state=api_related_state)
        if hasattr(self, 'service_account_file_label'): self.service_account_file_label.config(state=vertex_related_state)
        if hasattr(self, 'service_account_file_entry'): self.service_account_file_entry.config(state=vertex_related_state)
        if hasattr(self, 'browse_sa_file_button'): self.browse_sa_file_button.config(state=vertex_related_state)
        if hasattr(self, 'gcp_project_label'): self.gcp_project_label.config(state=vertex_related_state)
        if hasattr(self, 'gcp_project_entry'): self.gcp_project_entry.config(state=vertex_related_state)
        if hasattr(self, 'gcp_location_label'): self.gcp_location_label.config(state=vertex_related_state)
        if hasattr(self, 'gcp_location_entry'): self.gcp_location_entry.config(state=vertex_related_state)

    def _update_model_list_ui(self):
        if not self.ebtg_app_service or not self.ebtg_app_service.btg_app_service:
            messagebox.showerror("오류", "BTG AppService가 초기화되지 않았습니다.") # 이미 한국어
            return

        current_user_input_model = self.model_name_combobox.get()
        try:
            logging.getLogger(__name__).info("BTG 모델 목록 새로고침 중...")
            # Ensure BTG client is ready
            if not self.ebtg_app_service.btg_app_service.gemini_client:
                # Try to re-init BTG client by saving current BTG part of config
                btg_config_part = self._get_btg_config_from_ui()
                self.ebtg_app_service.btg_app_service.config.update(btg_config_part)
                self.ebtg_app_service.btg_app_service.load_app_config() # This re-initializes gemini_client
                if not self.ebtg_app_service.btg_app_service.gemini_client:
                    messagebox.showwarning("인증 필요", "BTG API 클라이언트 초기화 실패. API 키 또는 Vertex AI 설정을 확인하세요.") # 이미 한국어
                    return

            models_data: list[ModelInfoDTO] = self.ebtg_app_service.btg_app_service.get_available_models() # type: ignore
            
            model_display_names = sorted(list(set(
                m.get("short_name") or m.get("display_name") or m.get("name") # Use .get for dict access
                for m in models_data if isinstance(m, dict) and (m.get("short_name") or m.get("display_name") or m.get("name"))
            )))
            self.model_name_combobox['values'] = model_display_names
            
            config_model_name = self.ebtg_app_service.btg_app_service.config.get("model_name", "")
            config_model_short_name = config_model_name.split('/')[-1] if '/' in config_model_name else config_model_name

            if current_user_input_model and current_user_input_model in model_display_names:
                self.model_name_combobox.set(current_user_input_model)
            elif config_model_short_name and config_model_short_name in model_display_names:
                self.model_name_combobox.set(config_model_short_name)
            elif config_model_name and config_model_name in model_display_names:
                 self.model_name_combobox.set(config_model_name)
            elif model_display_names:
                self.model_name_combobox.set(model_display_names[0])
            else:
                self.model_name_combobox.set("")
            logging.getLogger(__name__).info(f"{len(model_display_names)}개 BTG 모델 로드 완료.")
        except (BtgApiClientException, BtgServiceException) as e:
            messagebox.showerror("API 오류", f"BTG 모델 목록 조회 실패: {e}") # 이미 한국어
        except Exception as e: # type: ignore
            messagebox.showerror("오류", f"BTG 모델 목록 조회 중 예상치 못한 오류: {e}") # 이미 한국어
            logging.getLogger(__name__).error(f"BTG 모델 목록 조회 중 오류: {e}", exc_info=True)

    def _get_ebtg_config_from_ui(self) -> dict:
        if not self.ebtg_app_service: return {}
        
        config_data = self.ebtg_app_service.config_manager.get_default_config() # Start with defaults
        
        # EBTG specific settings
        config_data["target_language"] = self.ebtg_app_service.config.get("target_language", "ko") # Keep existing or default
        config_data["universal_translation_prompt"] = self.universal_translation_prompt_text.get("1.0", tk.END).strip()
        try: # 새 파라미터 읽기
            config_data["xhtml_segment_target_chars"] = int(self.ebtg_xhtml_segment_target_chars_entry.get() or "4000")
        except ValueError:
            config_data["xhtml_segment_target_chars"] = 4000 # 기본값
            messagebox.showwarning("입력 오류", "EBTG XHTML 세그먼트 목표 문자 수는 숫자여야 합니다. 기본값(4000)으로 설정됩니다.")
        
        # BTG module related settings (to be stored in ebtg_config.json, under a sub-key or flattened)
        # The universal_translation_prompt from EBTG will also be used by BTG if EBTG calls BTG.
        # So, _get_btg_config_from_ui should also reflect this.
        # For now, BTG settings are flattened. The universal prompt is at EBTG's top level.
        btg_settings = self._get_btg_config_from_ui()
        config_data.update(btg_settings) # Flatten BTG settings into EBTG config

        # Path to btg_config.json (if EBTG is to manage a separate BTG config file)
        # For now, assume EBTG config holds all necessary BTG settings directly.
        # config_data["btg_config_path"] = self.ebtg_app_service.config.get("btg_config_path")
        
        return config_data

    def _get_btg_config_from_ui(self) -> dict:
        """Helper to get BTG specific settings from UI elements"""
        btg_config = {}
        api_keys_str = self.api_keys_text.get("1.0", tk.END).strip()
        btg_config["api_keys"] = [key.strip() for key in api_keys_str.splitlines() if key.strip()]
        btg_config["use_vertex_ai"] = self.use_vertex_ai_var.get()
        btg_config["service_account_file_path"] = self.service_account_file_entry.get().strip() or None
        btg_config["gcp_project"] = self.gcp_project_entry.get().strip() or None
        btg_config["gcp_location"] = self.gcp_location_entry.get().strip() or None
        btg_config["model_name"] = self.model_name_combobox.get().strip()
        btg_config["temperature"] = self.temperature_scale.get()
        btg_config["top_p"] = self.top_p_scale.get()
        
        try: btg_config["chunk_size"] = int(self.btg_chunk_size_entry.get() or "6000")
        except ValueError: btg_config["chunk_size"] = 6000
        try: btg_config["max_workers"] = int(self.btg_max_workers_entry.get() or "4")
        except ValueError: btg_config["max_workers"] = 4
        try: btg_config["requests_per_minute"] = int(self.btg_rpm_entry.get() or "60")
        except ValueError: btg_config["requests_per_minute"] = 60

        btg_config["novel_language"] = self.btg_novel_language_entry.get().strip() or "auto"
        btg_config["novel_language_fallback"] = self.btg_novel_language_fallback_entry.get().strip() or "ja"
        # "prompts" for BTG is now superseded by "universal_translation_prompt" from EBTG config
        # btg_config["prompts"] = self.btg_text_prompt_text.get("1.0", tk.END).strip() # This UI element will be removed

        btg_config["use_content_safety_retry"] = self.btg_use_content_safety_retry_var.get()
        try: btg_config["max_content_safety_split_attempts"] = int(self.btg_max_split_attempts_entry.get() or "3")
        except ValueError: btg_config["max_content_safety_split_attempts"] = 3
        try: btg_config["min_content_safety_chunk_size"] = int(self.btg_min_chunk_size_entry.get() or "100")
        except ValueError: btg_config["min_content_safety_chunk_size"] = 100
        
        btg_config["enable_dynamic_lorebook_injection"] = self.btg_enable_dynamic_lorebook_var.get()
        try: btg_config["max_lorebook_entries_per_chunk_injection"] = int(self.btg_max_lorebook_entries_injection_entry.get() or "3")
        except ValueError: btg_config["max_lorebook_entries_per_chunk_injection"] = 3
        try: btg_config["max_lorebook_chars_per_chunk_injection"] = int(self.btg_max_lorebook_chars_injection_entry.get() or "500")
        except ValueError: btg_config["max_lorebook_chars_per_chunk_injection"] = 500

        # BTG Lorebook Management Tab settings (these are also part of BTG config)
        btg_config["lorebook_json_path"] = self.btg_lorebook_json_path_entry.get().strip() or None
        btg_config["lorebook_sampling_ratio"] = self.btg_sample_ratio_scale.get()
        btg_config["lorebook_max_entries_per_segment"] = int(self.btg_max_entries_per_segment_spinbox.get() or "5")
        btg_config["lorebook_extraction_temperature"] = self.btg_extraction_temp_scale.get()
        btg_config["lorebook_sampling_method"] = self.btg_lorebook_sampling_method_combobox.get()
        btg_config["lorebook_max_chars_per_entry"] = int(self.btg_lorebook_max_chars_entry.get() or "200")
        btg_config["lorebook_keyword_sensitivity"] = self.btg_lorebook_keyword_sensitivity_combobox.get()
        btg_config["lorebook_chunk_size"] = int(self.btg_lorebook_chunk_size_entry.get() or "8000")
        try: btg_config["lorebook_priority_settings"] = json.loads(self.btg_lorebook_priority_text.get("1.0", tk.END).strip() or "{}")
        except json.JSONDecodeError: btg_config["lorebook_priority_settings"] = {"character": 5, "worldview": 5, "story_element": 5}
        # Dynamic lorebook injection settings from Lorebook Tab (if they are distinct)
        btg_config["enable_dynamic_lorebook_injection"] = self.btg_dyn_lb_enable_var_loretab.get() # From lorebook tab
        try: btg_config["max_lorebook_entries_per_chunk_injection"] = int(self.btg_dyn_lb_max_entries_entry_loretab.get() or "3")
        except ValueError: btg_config["max_lorebook_entries_per_chunk_injection"] = 3 # Default if empty/invalid
        try: btg_config["max_lorebook_chars_per_chunk_injection"] = int(self.btg_dyn_lb_max_chars_entry_loretab.get() or "500")
        except ValueError: btg_config["max_lorebook_chars_per_chunk_injection"] = 500
        
        return btg_config

    def _save_ebtg_settings(self):
        if not self.ebtg_app_service:
            messagebox.showerror("오류", "EBTG AppService가 초기화되지 않았습니다.")
            return
        try:
            config_to_save = self._get_ebtg_config_from_ui()
            self.ebtg_app_service.config_manager.save_config(config_to_save)
            # After saving, reload the config into the app_service instance
            self.ebtg_app_service.config = self.ebtg_app_service.config_manager.load_config()
            # And update BTG's config if it's managed separately or needs explicit update
            self.ebtg_app_service.btg_app_service.config.update(self._get_btg_config_from_ui())
            self.ebtg_app_service.btg_app_service.load_app_config() # Re-init BTG client if auth changed

            messagebox.showinfo("성공", "EBTG 설정이 성공적으로 저장되었습니다.") # 이미 한국어
            logging.getLogger(__name__).info("EBTG 설정 저장됨.")
        except Exception as e: # type: ignore
            messagebox.showerror("오류", f"EBTG 설정 저장 중 예상치 못한 오류: {e}") # 이미 한국어
            logging.getLogger(__name__).error(f"EBTG 설정 저장 중 오류: {e}", exc_info=True)

    def _load_ebtg_settings_to_ui(self):
        if not self.ebtg_app_service:
            logging.getLogger(__name__).warning("EBTG AppService 없음, UI에 설정 로드 불가.")
            return
        
        config = self.ebtg_app_service.config
        
        # EBTG specific settings
        self.universal_translation_prompt_text.delete('1.0', tk.END)
        self.universal_translation_prompt_text.insert('1.0', config.get("universal_translation_prompt", ""))
        self.ebtg_xhtml_segment_target_chars_entry.delete(0, tk.END) # 새 파라미터 UI 업데이트
        self.ebtg_xhtml_segment_target_chars_entry.insert(0, str(config.get("xhtml_segment_target_chars", 4000)))

        # BTG module related settings
        self.api_keys_text.delete('1.0', tk.END)
        self.api_keys_text.insert('1.0', "\n".join(config.get("api_keys", [])))
        self.use_vertex_ai_var.set(config.get("use_vertex_ai", False))
        self.service_account_file_entry.delete(0, tk.END) 
        self.service_account_file_entry.insert(0, config.get("service_account_file_path") or "") # Ensure string
        self.gcp_project_entry.delete(0, tk.END)
        self.gcp_project_entry.insert(0, config.get("gcp_project") or "") # Applied similar pattern
        self.gcp_location_entry.delete(0, tk.END)
        self.gcp_location_entry.insert(0, config.get("gcp_location") or "") # Applied similar pattern
        self.model_name_combobox.set(config.get("model_name", "gemini-2.0-flash"))
        
        try: self.temperature_scale.set(float(config.get("temperature", 0.7)))
        except ValueError: self.temperature_scale.set(0.7)
        self.temperature_label.config(text=f"{self.temperature_scale.get():.2f}")
        try: self.top_p_scale.set(float(config.get("top_p", 0.9)))
        except ValueError: self.top_p_scale.set(0.9)
        self.top_p_label.config(text=f"{self.top_p_scale.get():.2f}")

        self.btg_chunk_size_entry.delete(0, tk.END)
        self.btg_chunk_size_entry.insert(0, str(config.get("chunk_size", 6000)))
        self.btg_max_workers_entry.delete(0, tk.END)
        self.btg_max_workers_entry.insert(0, str(config.get("max_workers", 4)))
        self.btg_rpm_entry.delete(0, tk.END)
        self.btg_rpm_entry.insert(0, str(config.get("requests_per_minute", 60)))

        self.btg_novel_language_entry.delete(0, tk.END)
        self.btg_novel_language_entry.insert(0, config.get("novel_language", "auto"))
        self.btg_novel_language_fallback_entry.delete(0, tk.END)
        self.btg_novel_language_fallback_entry.insert(0, config.get("novel_language_fallback", "ja"))

        self.btg_use_content_safety_retry_var.set(config.get("use_content_safety_retry", True))
        self.btg_max_split_attempts_entry.delete(0, tk.END)
        self.btg_max_split_attempts_entry.insert(0, str(config.get("max_content_safety_split_attempts", 3)))
        self.btg_min_chunk_size_entry.delete(0, tk.END)
        self.btg_min_chunk_size_entry.insert(0, str(config.get("min_content_safety_chunk_size", 100)))

        self.btg_enable_dynamic_lorebook_var.set(config.get("enable_dynamic_lorebook_injection", False))
        self.btg_max_lorebook_entries_injection_entry.delete(0, tk.END)
        self.btg_max_lorebook_entries_injection_entry.insert(0, str(config.get("max_lorebook_entries_per_chunk_injection", 3)))
        self.btg_max_lorebook_chars_injection_entry.delete(0, tk.END)
        self.btg_max_lorebook_chars_injection_entry.insert(0, str(config.get("max_lorebook_chars_per_chunk_injection", 500)))

        # Load BTG Lorebook Management Tab settings
        self.btg_lorebook_json_path_entry.delete(0, tk.END)
        # Ensure that a string is always passed to insert, handling None from config.get
        self.btg_lorebook_json_path_entry.insert(0, config.get("lorebook_json_path") or "")
        self.btg_sample_ratio_scale.set(config.get("lorebook_sampling_ratio", 25.0))
        self.btg_sample_ratio_label.config(text=f"{self.btg_sample_ratio_scale.get():.1f}%")
        self.btg_max_entries_per_segment_spinbox.set(str(config.get("lorebook_max_entries_per_segment", 5)))
        self.btg_extraction_temp_scale.set(config.get("lorebook_extraction_temperature", 0.2))
        self.btg_extraction_temp_label.config(text=f"{self.btg_extraction_temp_scale.get():.2f}")
        self.btg_lorebook_sampling_method_combobox.set(config.get("lorebook_sampling_method", "uniform"))
        self.btg_lorebook_max_chars_entry.delete(0, tk.END)
        self.btg_lorebook_max_chars_entry.insert(0, str(config.get("lorebook_max_chars_per_entry", 200)))
        self.btg_lorebook_keyword_sensitivity_combobox.set(config.get("lorebook_keyword_sensitivity", "medium"))
        self.btg_lorebook_chunk_size_entry.delete(0, tk.END)
        self.btg_lorebook_chunk_size_entry.insert(0, str(config.get("lorebook_chunk_size", 8000)))
        self.btg_lorebook_priority_text.delete('1.0', tk.END)
        self.btg_lorebook_priority_text.insert('1.0', json.dumps(config.get("lorebook_priority_settings", {"character": 5, "worldview": 5, "story_element": 5}), indent=2))
        
        # Load dynamic lorebook injection settings on the Lorebook tab
        self.btg_dyn_lb_enable_var_loretab.set(config.get("enable_dynamic_lorebook_injection", False))
        self.btg_dyn_lb_max_entries_entry_loretab.delete(0, tk.END)
        self.btg_dyn_lb_max_entries_entry_loretab.insert(0, str(config.get("max_lorebook_entries_per_chunk_injection", 3)))
        self.btg_dyn_lb_max_chars_entry_loretab.delete(0, tk.END)
        self.btg_dyn_lb_max_chars_entry_loretab.insert(0, str(config.get("max_lorebook_chars_per_chunk_injection", 500)))

        self._toggle_vertex_fields() # Update UI state based on loaded config
        logging.getLogger(__name__).info("EBTG 설정 UI에 로드 완료.")

    def _translation_task_runner(self, input_path, output_path):
        try:
            if not self.ebtg_app_service:
                logging.getLogger(__name__).error("EBTG App Service not available for translation.")
                self.status_var.set("오류: 서비스가 준비되지 않았습니다.")
                return

            # Ensure latest settings from UI are applied to app_service.config
            # and subsequently to btg_app_service's config before translation.
            # This also handles lorebook_json_path for BTG's TranslationService.
            current_ui_config = self._get_ebtg_config_from_ui()
            self.ebtg_app_service.config.update(current_ui_config)

            # Update BTG AppService config within EbtgAppService
            # This ensures BTG uses the latest settings, including lorebook path for dynamic injection.
            if hasattr(self.ebtg_app_service, 'btg_app_service') and self.ebtg_app_service.btg_app_service:
                btg_part_of_config = self._get_btg_config_from_ui()
                self.ebtg_app_service.btg_app_service.config.update(btg_part_of_config)
                self.ebtg_app_service.btg_app_service.load_app_config() # This re-initializes gemini_client if auth changed

            # --- 진행률 콜백 전달 ---
            # EbtgAppService.translate_epub이 progress_callback을 받도록 수정되었다고 가정
            # progress_dto는 EpubProcessingProgressDTO 타입
            # _update_epub_translation_progress 메서드가 콜백으로 사용됨

            self.status_var.set(f"처리 중: {Path(input_path).name}...")
            logging.getLogger(__name__).info(f"Starting translation via GUI: {input_path} -> {output_path}")
            
            # The core translation call, passing the GUI update callback
            self.ebtg_app_service.translate_epub(
                input_path, output_path, progress_callback=self._update_epub_translation_progress
            )

            if self._stop_event.is_set(): # Check if stop was requested
                logging.getLogger(__name__).info("Translation process was requested to stop.")
                self.status_var.set("사용자에 의해 번역이 중지되었습니다.")
            else:
                logging.getLogger(__name__).info("Translation completed successfully.")
                self.status_var.set("번역 완료!")
        except EbtgProcessingError as e:
            logging.getLogger(__name__).error(f"EBTG Processing Error: {e}", exc_info=False) # exc_info=False to avoid huge tracebacks in GUI log for known errors
            self.status_var.set(f"오류: {e}")
        except Exception as e: # type: ignore
            logging.getLogger(__name__).error(f"An unexpected error occurred during translation: {e}", exc_info=True)
            self.status_var.set(f"예상치 못한 오류: 로그를 확인하세요.")
        finally:
            if hasattr(self, 'start_button'): self.start_button.config(state=tk.NORMAL)
            if hasattr(self, 'stop_button'): self.stop_button.config(state=tk.DISABLED)
            self._stop_event.clear() 

    def start_translation(self):
        input_path: str = self.input_epub_var.get()
        output_path: str = self.output_epub_var.get()

        if not input_path or not output_path: # type: ignore
            self.status_var.set("오류: 입력 및 출력 경로가 필요합니다.")
            return
        if not Path(input_path).exists():
            self.status_var.set(f"Error: Input file not found: {input_path}")
            return

        if self.translation_thread and self.translation_thread.is_alive():
            self.status_var.set("오류: 이미 번역이 진행 중입니다.")
            logging.getLogger(__name__).warning("GUI: Start pressed while a translation is ongoing.")
            return

        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_var.set("번역 시작 중...")
        
        # --- EbtgAppService.translate_epub에 콜백 전달 ---
        # EbtgAppService.translate_epub이 progress_callback 인자를 받도록 수정되었다고 가정
        # def progress_update_for_service(progress_dto: EpubProcessingProgressDTO):
        #     # This function is called from the EbtgAppService thread.
        #     # We need to schedule the GUI update in the main thread.
        #     if self.root.winfo_exists():
        #         self.root.after(0, self._update_epub_translation_progress, progress_dto)

        self._stop_event.clear()
        self.translation_thread = threading.Thread(
            target=self._translation_task_runner, # Use the original runner, callback is passed inside it
            args=(input_path, output_path), # Callback is handled by translate_epub now
            daemon=True
        )
        self.translation_thread.start()

    def request_stop_translation(self):
        if self.translation_thread and self.translation_thread.is_alive():
            logging.getLogger(__name__).info("Stop requested by user.")
            self.status_var.set("중지 요청됨... (가능한 경우 현재 파일/세그먼트 이후 중지)")
            self._stop_event.set() 
            # Stop button will be re-enabled/disabled in _translation_task_runner finally block
            # For immediate feedback, disable it here too.
            self.stop_button.config(state=tk.DISABLED)
        else:
            self.status_var.set("중지할 활성 번역 작업이 없습니다.")
            self.stop_button.config(state=tk.DISABLED)
            self.start_button.config(state=tk.NORMAL)

    def _update_epub_translation_progress(self, progress_dto: EpubProcessingProgressDTO):
        """
        Updates the GUI with EPUB translation progress.
        This method is called via self.root.after() to ensure it runs in the main GUI thread.
        `progress_dto` is an instance of the presumed `EpubProcessingProgressDTO`.
        """
        # Schedule the actual GUI update to run in the main thread
        if self.root.winfo_exists():
            self.root.after(0, self._do_update_epub_progress_widgets, progress_dto)

    def _do_update_epub_progress_widgets(self, progress_dto: EpubProcessingProgressDTO):
        if not self.root.winfo_exists():
            return

        if progress_dto.total_files > 0:
            progress_percentage = (progress_dto.processed_files / progress_dto.total_files) * 100
            self.progress_bar['value'] = progress_percentage
        else:
            self.progress_bar['value'] = 0

        status_msg = f"{progress_dto.status_message} "
        if progress_dto.current_file_name: status_msg += f"({progress_dto.current_file_name}) "
        status_msg += f"{progress_dto.processed_files}/{progress_dto.total_files} 파일"
        if progress_dto.errors_count > 0: status_msg += f", Errors: {progress_dto.errors_count}"
        self.status_var.set(status_msg)

    def _update_lorebook_extraction_progress(self, dto: LorebookExtractionProgressDTO):
        def _update():
            if not self.root.winfo_exists(): return
            msg = f"{dto.current_status_message} ({dto.processed_segments}/{dto.total_segments}, 추출 항목: {dto.extracted_entries_count})"
            self.btg_lorebook_progress_label.config(text=msg)
        if self.root.winfo_exists():
            self.root.after(0, _update)

    def _extract_lorebook_from_epub_thread(self):
        if not self.ebtg_app_service or not self.ebtg_app_service.btg_app_service:
            messagebox.showerror("오류", "BTG AppService가 초기화되지 않았습니다.") # 이미 한국어
            return

        input_epub_path = self.input_epub_var.get()
        if not input_epub_path:
            messagebox.showwarning("경고", "로어북을 추출할 EPUB 파일을 먼저 선택해주세요.") # 이미 한국어
            return
        if not Path(input_epub_path).exists():
            messagebox.showerror("오류", f"EPUB 파일을 찾을 수 없습니다: {input_epub_path}") # 이미 한국어
            return

        try:
            # Apply current BTG settings from UI to BTG AppService config
            btg_config_part = self._get_btg_config_from_ui()
            self.ebtg_app_service.btg_app_service.config.update(btg_config_part)
            # This load_app_config will re-initialize TranslationService with the new config, including lorebook_json_path
            self.ebtg_app_service.btg_app_service.load_app_config() # Re-init client if needed

            if not self.ebtg_app_service.btg_app_service.gemini_client:
                if not messagebox.askyesno("API 설정 경고", "BTG API 클라이언트가 초기화되지 않았습니다. 계속 진행하시겠습니까?"): # 이미 한국어
                    return
        except Exception as e: # type: ignore
            messagebox.showerror("오류", f"로어북 추출 시작 전 BTG 설정 오류: {e}") # 이미 한국어
            logging.getLogger(__name__).error(f"로어북 추출 전 BTG 설정 오류: {e}", exc_info=True)
            return

        self.btg_lorebook_progress_label.config(text="EPUB 텍스트 취합 중...")
        logging.getLogger(__name__).info(f"EPUB에서 로어북 추출 시작: {input_epub_path}")

        def _extraction_task_wrapper():
            try:
                # Call EbtgAppService to get all text from the EPUB
                if not self.ebtg_app_service:
                    raise Exception("EBTG AppService is not initialized.")
                
                epub_full_text = self.ebtg_app_service.get_all_text_from_epub(input_epub_path)
                if epub_full_text is None: # Handle case where text extraction might fail or return None
                    self.root.after(0, lambda: messagebox.showerror("오류", "EPUB에서 텍스트를 추출하지 못했습니다.")) # 이미 한국어
                    self.root.after(0, lambda: self.btg_lorebook_progress_label.config(text="EPUB 텍스트 추출 실패"))
                    return

                if not epub_full_text.strip():
                    self.root.after(0, lambda: messagebox.showinfo("정보", "EPUB에서 추출할 텍스트 내용이 없습니다.")) # 이미 한국어
                    self.root.after(0, lambda: self.btg_lorebook_progress_label.config(text="추출할 텍스트 없음")) # 이미 한국어
                    return

                # novel_language_code from BTG settings UI
                novel_lang_for_extraction = self.ebtg_app_service.btg_app_service.config.get("novel_language")
                
                result_json_path = self.ebtg_app_service.btg_app_service.extract_lorebook(
                    novel_text_content=epub_full_text,
                    input_file_path_for_naming=input_epub_path, # Use EPUB path for naming output
                    progress_callback=self._update_lorebook_extraction_progress,
                    novel_language_code=novel_lang_for_extraction,
                    seed_lorebook_path=self.btg_lorebook_json_path_entry.get() or None # Use seed if specified
                )
                self.root.after(0, lambda: messagebox.showinfo("성공", f"로어북 추출 완료!\n결과 파일: {result_json_path}")) # 이미 한국어
                self.root.after(0, lambda: self.btg_lorebook_progress_label.config(text=f"추출 완료: {result_json_path.name}"))
                self.root.after(0, lambda: self.btg_lorebook_json_path_entry.insert(0, str(result_json_path))) # Update path entry
                if result_json_path and result_json_path.exists():
                    with open(result_json_path, 'r', encoding='utf-8') as f_res:
                        self.root.after(0, lambda: self._display_btg_lorebook_content(f_res.read()))
            except (BtgFileHandlerException, BtgApiClientException, BtgServiceException, BtgBusinessLogicException) as e_btg:
                logging.getLogger(__name__).error(f"로어북 추출 중 BTG 예외: {e_btg}", exc_info=True)
                self.root.after(0, lambda: messagebox.showerror("추출 오류", f"로어북 추출 중 오류: {e_btg}")) # 이미 한국어
            except Exception as e_unknown: # type: ignore
                logging.getLogger(__name__).error(f"로어북 추출 중 알 수 없는 예외: {e_unknown}", exc_info=True)
                self.root.after(0, lambda: messagebox.showerror("알 수 없는 오류", f"로어북 추출 중 예상치 못한 오류: {e_unknown}")) # 이미 한국어
            finally:
                logging.getLogger(__name__).info("로어북 추출 스레드 종료.") # 이미 한국어

        thread = threading.Thread(target=_extraction_task_wrapper, daemon=True)
        thread.start()

    def _display_btg_lorebook_content(self, content: str):
        self.btg_lorebook_display_text.config(state=tk.NORMAL)
        self.btg_lorebook_display_text.delete('1.0', tk.END)
        self.btg_lorebook_display_text.insert('1.0', content)
        self.btg_lorebook_display_text.config(state=tk.DISABLED)

    def _load_btg_lorebook_to_display(self):
        filepath = filedialog.askopenfilename(title="로어북 JSON 파일 선택", filetypes=(("JSON 파일", "*.json"), ("모든 파일", "*.*"))) # 이미 한국어
        if filepath:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                self._display_btg_lorebook_content(content)
                self.btg_lorebook_json_path_entry.delete(0, tk.END)
                self.btg_lorebook_json_path_entry.insert(0, filepath)
                logging.getLogger(__name__).info(f"BTG 로어북 파일 로드됨: {filepath}")
            except Exception as e: # type: ignore
                messagebox.showerror("오류", f"로어북 파일 로드 실패: {e}") # 이미 한국어

    def _copy_btg_lorebook_json(self):
        content = self.btg_lorebook_display_text.get('1.0', tk.END).strip()
        if content:
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            messagebox.showinfo("성공", "로어북 JSON 내용이 클립보드에 복사되었습니다.") # 이미 한국어
        else:
            messagebox.showwarning("경고", "복사할 내용이 없습니다.") # 이미 한국어

    def _save_displayed_btg_lorebook_json(self):
        content = self.btg_lorebook_display_text.get('1.0', tk.END).strip()
        if not content:
            messagebox.showwarning("경고", "저장할 내용이 없습니다.") # 이미 한국어
            return
        filepath = filedialog.asksaveasfilename(title="로어북 JSON으로 저장", defaultextension=".json", filetypes=(("JSON 파일", "*.json"), ("모든 파일", "*.*"))) # 이미 한국어
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                messagebox.showinfo("성공", f"로어북이 성공적으로 저장되었습니다: {filepath}") # 이미 한국어
            except Exception as e: # type: ignore
                messagebox.showerror("오류", f"로어북 저장 실패: {e}") # 이미 한국어


if __name__ == '__main__':
    # This allows direct execution of the GUI script for testing.
    # Ensure ebtg_app_service.py and other dependencies are in the PYTHONPATH
    # or in a structure that Python can find (e.g., running from project root).
    
    # Basic console logging for issues that occur before GUI handler is fully set up
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s') # Line 876

    root_tk_window = tk.Tk() # Indent this line
    app_gui = EbtgGui(root_tk_window) # Indent this line
    root_tk_window.mainloop() # Indent this line