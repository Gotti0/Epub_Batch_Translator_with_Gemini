# ebtg/ebtg_gui.py

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
import logging
import threading
import queue # For thread-safe log communication
from pathlib import Path

# Assuming EbtgAppService is in the same directory or package
try:
    from ebtg.ebtg_app_service import EbtgAppService
    # from .config_manager import EbtgConfigManager # Not directly used by GUI for settings editing in this version
    from ebtg.ebtg_exceptions import EbtgProcessingError
except ImportError: # For running script directly for testing
    # This block allows running the GUI script directly if it's in the project root
    # and other modules are discoverable (e.g., by adding project root to PYTHONPATH)
    from ebtg_app_service import EbtgAppService
    # from config_manager import EbtgConfigManager
    from ebtg_exceptions import EbtgProcessingError


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
                self.text_widget.configure(state='normal')
                self.text_widget.insert(tk.END, record + '\n')
                self.text_widget.configure(state='disabled')
                self.text_widget.see(tk.END) # Scroll to the end
        # Schedule the next poll
        self.text_widget.after(100, self.poll_log_queue)


class EbtgGui:
    def __init__(self, root_window):
        self.root = root_window
        self.root.title("EBTG - EPUB Batch Translator with Gemini")
        self.root.geometry("800x600")

        self.ebtg_app_service: EbtgAppService | None = None
        self.translation_thread: threading.Thread | None = None
        self._stop_event = threading.Event() 

        # --- Main Frame ---
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- File Selection Frame ---
        file_frame = ttk.LabelFrame(main_frame, text="File Selection", padding="10")
        file_frame.pack(fill=tk.X, pady=5)

        ttk.Label(file_frame, text="Input EPUB:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.input_epub_var = tk.StringVar()
        self.input_epub_entry = ttk.Entry(file_frame, textvariable=self.input_epub_var, width=60)
        self.input_epub_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.browse_input_btn = ttk.Button(file_frame, text="Browse...", command=self.browse_input_file)
        self.browse_input_btn.grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(file_frame, text="Output EPUB:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.output_epub_var = tk.StringVar()
        self.output_epub_entry = ttk.Entry(file_frame, textvariable=self.output_epub_var, width=60)
        self.output_epub_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
        self.browse_output_btn = ttk.Button(file_frame, text="Browse...", command=self.browse_output_path)
        self.browse_output_btn.grid(row=1, column=2, padx=5, pady=5)
        
        file_frame.columnconfigure(1, weight=1)

        # --- Controls Frame ---
        controls_frame = ttk.Frame(main_frame, padding="10")
        controls_frame.pack(fill=tk.X, pady=5)

        self.start_button = ttk.Button(controls_frame, text="Start Translation", command=self.start_translation)
        self.start_button.pack(side=tk.LEFT, padx=5)
        
        self.stop_button = ttk.Button(controls_frame, text="Stop", command=self.request_stop_translation, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        self.status_var = tk.StringVar(value="Ready.")
        status_label = ttk.Label(controls_frame, textvariable=self.status_var)
        status_label.pack(side=tk.RIGHT, padx=5)

        # --- Log Display Frame ---
        log_frame = ttk.LabelFrame(main_frame, text="Logs", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state=tk.DISABLED, height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self.setup_logging()
        
        try:
            self.ebtg_app_service = EbtgAppService() # Uses default config path
            logging.getLogger(__name__).info("EBTG App Service initialized by GUI.")
        except Exception as e:
            self.log_text.configure(state='normal')
            self.log_text.insert(tk.END, f"CRITICAL: Error initializing EBTG App Service: {e}\nCheck console for details. GUI may not function.\n")
            self.log_text.configure(state='disabled')
            self.start_button.config(state=tk.DISABLED)
            logging.getLogger(__name__).critical(f"Failed to initialize EbtgAppService in GUI: {e}", exc_info=True)

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
            title="Select Input EPUB File",
            filetypes=(("EPUB files", "*.epub"), ("All files", "*.*"))
        )
        if filepath:
            self.input_epub_var.set(filepath)
            p = Path(filepath)
            suggested_output = p.parent / f"{p.stem}_translated.epub"
            self.output_epub_var.set(str(suggested_output))

    def browse_output_path(self):
        filepath = filedialog.asksaveasfilename(
            title="Select Output EPUB File Path",
            defaultextension=".epub",
            filetypes=(("EPUB files", "*.epub"), ("All files", "*.*"))
        )
        if filepath:
            self.output_epub_var.set(filepath)

    def _translation_task_runner(self, input_path, output_path):
        try:
            if not self.ebtg_app_service:
                logging.getLogger(__name__).error("EBTG App Service not available for translation.")
                self.status_var.set("Error: Service not ready.")
                return

            self.status_var.set(f"Processing: {Path(input_path).name}...")
            logging.getLogger(__name__).info(f"Starting translation via GUI: {input_path} -> {output_path}")
            
            # The core translation call
            self.ebtg_app_service.translate_epub(input_path, output_path) 
            
            if self._stop_event.is_set():
                logging.getLogger(__name__).info("Translation process was requested to stop.")
                self.status_var.set("Translation stopped by user.")
            else:
                logging.getLogger(__name__).info("Translation completed successfully.")
                self.status_var.set("Translation complete!")
        except EbtgProcessingError as e:
            logging.getLogger(__name__).error(f"EBTG Processing Error: {e}", exc_info=False) # exc_info=False to avoid huge tracebacks in GUI log for known errors
            self.status_var.set(f"Error: {e}")
        except Exception as e:
            logging.getLogger(__name__).error(f"An unexpected error occurred during translation: {e}", exc_info=True)
            self.status_var.set(f"Unexpected Error: Check logs.")
        finally:
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self._stop_event.clear() 

    def start_translation(self):
        input_path = self.input_epub_var.get()
        output_path = self.output_epub_var.get()

        if not input_path or not output_path:
            self.status_var.set("Error: Input and Output paths are required.")
            logging.getLogger(__name__).error("GUI: Input or Output path missing.")
            return
        
        if not Path(input_path).exists():
            self.status_var.set(f"Error: Input file not found: {input_path}")
            logging.getLogger(__name__).error(f"GUI: Input file not found: {input_path}")
            return

        if self.translation_thread and self.translation_thread.is_alive():
            self.status_var.set("Error: A translation is already in progress.")
            logging.getLogger(__name__).warning("GUI: Start pressed while a translation is ongoing.")
            return

        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_var.set("Starting translation...")
        
        self._stop_event.clear()
        self.translation_thread = threading.Thread(
            target=self._translation_task_runner, 
            args=(input_path, output_path),
            daemon=True 
        )
        self.translation_thread.start()

    def request_stop_translation(self):
        if self.translation_thread and self.translation_thread.is_alive():
            logging.getLogger(__name__).info("Stop requested by user.")
            self.status_var.set("Stop requested... (will stop after current file/segment if possible)")
            self._stop_event.set() 
            self.stop_button.config(state=tk.DISABLED) 
        else:
            self.status_var.set("No active translation to stop.")
            self.stop_button.config(state=tk.DISABLED)
            self.start_button.config(state=tk.NORMAL)


if __name__ == '__main__':
    # This allows direct execution of the GUI script for testing.
    # Ensure ebtg_app_service.py and other dependencies are in the PYTHONPATH
    # or in a structure that Python can find (e.g., running from project root).
    
    # Basic console logging for issues that occur before GUI handler is fully set up
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    root_tk_window = tk.Tk()
    app_gui = EbtgGui(root_tk_window)
    root_tk_window.mainloop()