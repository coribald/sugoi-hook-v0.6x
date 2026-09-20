import tkinter as tk
try:
    import tkinter.font as tkfont
except ImportError:
    tkfont = None
from plugins import HookPlugin
from dictionary_backend import JitendexDictionary, extract_entry_glossaries_and_examples
import sys
import json
import re
import logging
from pathlib import Path

from json_persistence import JsonPersistenceError, load_json_object, save_json_object_atomic

DICTIONARY_LOOKUP_CHAR_PATTERN = re.compile(r'[一-龯々〆ヶぁ-ゖァ-ヺー]')

FRIENDLY_RULE_LABELS = {
    "adj-i": "i-adjective",
    "v1": "Ichidan verb",
    "v5": "Godan verb",
    "vk": "kuru verb",
    "vs": "suru verb",
    "vz": "zuru verb",
}


def runtime_debug_logging_enabled() -> bool:
    return '--debug' in sys.argv or getattr(sys, '_sugoihook_debug_logging', False)

def get_runtime_user_data_path() -> Path:
    argv0 = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None
    executable = Path(sys.executable).resolve()

    if argv0 and argv0.suffix.lower() == '.exe' and argv0 != executable:
        return argv0.parent

    if executable.suffix.lower() == '.exe' and 'python' not in executable.name.lower():
        return executable.parent

    return Path(__file__).parent.parent


class OverlayWindowPlugin(HookPlugin):
    name = "Overlay Window"
    description = "Displays text in a transparent overlay window."
    version = "2.0"
    author = "Cline"

    DICTIONARY_DEFAULTS = {
        'dictionary_enabled': True,
        'dictionary_width': 480,
        'dictionary_entry_font': 'Segoe UI',
        'dictionary_entry_font_size': 18,
        'dictionary_entry_color': '#f9e2af',
        'dictionary_definition_font': 'Segoe UI',
        'dictionary_definition_font_size': 15,
        'dictionary_definition_color': '#a6adc8',
        'dictionary_meta_font': 'Segoe UI',
        'dictionary_meta_font_size': 11,
        'dictionary_meta_color': '#a6adc8',
        'dictionary_example_jp_font': 'Segoe UI',
        'dictionary_example_jp_font_size': 14,
        'dictionary_example_jp_color': '#a6adc8',
        'dictionary_example_en_font': 'Segoe UI',
        'dictionary_example_en_font_size': 14,
        'dictionary_example_en_color': '#f9e2af',
    }

    def __init__(self):
        super().__init__()
        self.enabled = False # Disabled by default
        self.overlay = None
        self.text_widget = None
        self.dictionary_text = None
        self.drag_data = {"x": 0, "y": 0}
        self.save_after_id = None
        self.dictionary_backend = None
        self.dictionary_status_after_id = None
        self.dictionary_lookup_char_pattern = DICTIONARY_LOOKUP_CHAR_PATTERN
        self._last_dictionary_status_log = None
        
        # Default configuration
        self.config = {
            'bg_color': '#1e1e2e',
            'translation_font': 'Segoe UI',
            'translation_font_size': 14,
            'translation_bold': True,
            'translation_color': '#89b4fa',
            'original_font': 'Segoe UI',
            'original_font_size': 10,
            'original_color': '#a6adc8',
            'warning_font': 'Segoe UI',
            'warning_font_size': 12,
            'warning_italic': True,
            'warning_color': '#f9e2af',
            'window_opacity': 80,
            'close_btn_color': '#f38ba8',
            'border_color': '#585b70',
            'min_width': 400,
            'max_width': 1200,
            'min_height': 100,
            'max_height': 300,
            'default_width': 900,
            'default_height': 200,
            'window_x': 100,
            'window_y': 100,
        }
        
        # Load saved configuration
        self.load_config()
        self._apply_dictionary_defaults()

    def _debug(self, event, **kwargs):
        if not runtime_debug_logging_enabled():
            return
        if kwargs:
            details = " | ".join(f"{key}={value}" for key, value in kwargs.items())
            message = f"[OVERLAY] {event} | {details}"
        else:
            message = f"[OVERLAY] {event}"
        try:
            logging.info(message)
        except Exception:
            pass
        try:
            print(message, flush=True)
        except Exception:
            pass

    def _format_rules_label(self, rules_text):
        rules_text = (rules_text or "").strip()
        if not rules_text:
            return ""
        parts = [part for part in rules_text.split() if part]
        friendly_parts = [FRIENDLY_RULE_LABELS.get(part, part) for part in parts]
        return ", ".join(friendly_parts)

    def load_config(self):
        """Load configuration from JSON file"""
        try:
            config_path = self.get_config_path()
            saved_config, recovered_from_backup = load_json_object(config_path, self._is_valid_config)
        except JsonPersistenceError as error:
            self._report_config_issue(error)
            return
        if saved_config is not None:
            self.config.update(saved_config)
        if recovered_from_backup:
            self._report_config_issue("the primary file was invalid; recovered the last valid overlay settings")

    def _apply_dictionary_defaults(self):
        for key, value in self.DICTIONARY_DEFAULTS.items():
            self.config.setdefault(key, value)

    def save_config(self):
        """Save configuration to JSON file"""
        try:
            config_path = self.get_config_path()
            save_json_object_atomic(config_path, self.config, self._is_valid_config)
            return True
        except JsonPersistenceError as error:
            self._report_config_issue(error)
            return False

    def _report_config_issue(self, error):
        config_path = self.get_config_path()
        message = f"Could not use saved overlay settings in {config_path.name}: {error}"
        logging.warning(message)
        app = getattr(self, 'app', None)
        if app is not None and hasattr(app, 'report_config_issue'):
            app.report_config_issue(config_path, error)

    def _is_valid_config(self, config):
        if not all(isinstance(key, str) for key in config):
            return False
        for key, value in config.items():
            if key in self.config and type(value) is not type(self.config[key]):
                return False
        return True

    def get_config_path(self) -> Path:
        app = getattr(self, 'app', None)
        user_data_dir = getattr(app, 'user_data_dir', None)
        if user_data_dir:
            return Path(user_data_dir) / "overlay_config.json"
        return get_runtime_user_data_path() / "overlay_config.json"

    def on_enable(self):
        self.load_config()
        self._apply_dictionary_defaults()
        self.create_overlay()
        self.init_dictionary_system()

    def _get_effective_min_width(self):
        min_width = int(self.config.get('min_width', 400))
        if self.config.get('dictionary_enabled', True):
            dictionary_width = int(self.config.get('dictionary_width', 480))
            text_area_min_width = 320
            frame_padding = 44
            min_width = max(min_width, dictionary_width + text_area_min_width + frame_padding)
        return min_width

    def on_disable(self):
        if self.dictionary_status_after_id and self.overlay:
            try:
                self.overlay.after_cancel(self.dictionary_status_after_id)
            except Exception:
                pass
            self.dictionary_status_after_id = None
        if self.overlay:
            self.capture_overlay_geometry()
            self.flush_save_config()
            self.overlay.destroy()
            self.overlay = None
            self.text_widget = None
            self.dictionary_text = None
            self.dictionary_backend = None
            self._last_dictionary_status_log = None
            self._debug("disabled")

    def create_overlay(self):
        if self.overlay:
            return

        # Create a Toplevel window
        try:
            self.overlay = tk.Toplevel()
        except Exception:
            return

        self.overlay.title("Text Overlay")
        
        # Set min/max size constraints from config
        effective_min_width = self._get_effective_min_width()
        self.overlay.minsize(effective_min_width, self.config['min_height'])
        self.overlay.maxsize(self.config['max_width'], self.config['max_height'])

        # Initial geometry from config
        initial_width = max(int(self.config['default_width']), effective_min_width)
        self.overlay.geometry(
            f"{initial_width}x{self.config['default_height']}+{self.config['window_x']}+{self.config['window_y']}"
        )
        
        # Remove window decorations (title bar, borders)
        self.overlay.overrideredirect(True)
        
        # Keep window always on top
        self.overlay.attributes('-topmost', True)
        
        # Set transparency (alpha) from config
        self.overlay.attributes('-alpha', self.config['window_opacity'] / 100.0)
        
        # Set background color from config
        bg_color = self.config['bg_color']
        self.overlay.configure(bg=bg_color)
        self._debug(
            "create_overlay",
            width=initial_width,
            height=self.config['default_height'],
            x=self.config['window_x'],
            y=self.config['window_y']
        )

        # Make it draggable
        self.overlay.bind('<Button-1>', self.start_move)
        self.overlay.bind('<B1-Motion>', self.do_move)
        self.overlay.bind('<Configure>', self.on_overlay_configure)
        
        # Add a close button with configurable color
        close_btn = tk.Label(self.overlay, text="x", bg=bg_color,
                            fg=self.config['close_btn_color'],
                            font=("Arial", 14, "bold"), cursor="hand2")
        close_btn.place(relx=1.0, x=-10, y=0, anchor="ne")
        close_btn.bind("<Button-1>", self.hide_overlay)

        content_frame = tk.Frame(self.overlay, bg=bg_color)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        text_frame = tk.Frame(content_frame, bg=bg_color)
        text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        dictionary_frame = None
        if self.config.get('dictionary_enabled', True):
            dictionary_frame = tk.Frame(content_frame, bg=bg_color, width=self.config.get('dictionary_width', 480))
            dictionary_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(12, 0))
            dictionary_frame.pack_propagate(False)

        # Use Text widget for rich formatting
        self.text_widget = tk.Text(
            text_frame,
            bg=bg_color,
            fg=self.config['translation_color'],
            font=(self.config['translation_font'], self.config['translation_font_size']),
            wrap=tk.WORD,
            borderwidth=0,
            highlightthickness=0,
            state='disabled',
            cursor="arrow"
        )
        self.text_widget.pack(fill=tk.BOTH, expand=True)
        if self.config.get('dictionary_enabled', True):
            self.text_widget.bind('<ButtonRelease-1>', self.on_text_single_click, add="+")
            self.text_widget.bind('<Double-Button-1>', self.on_text_double_click, add="+")

        # Configure tags for formatting with config values
        original_font_style = (self.config['original_font'], self.config['original_font_size'])
        self.text_widget.tag_config("original",
                                   foreground=self.config['original_color'],
                                   font=original_font_style)
        
        translation_font_style = [self.config['translation_font'], self.config['translation_font_size']]
        if self.config['translation_bold']:
            translation_font_style.append('bold')
        self.text_widget.tag_config("translation",
                                   foreground=self.config['translation_color'],
                                   font=tuple(translation_font_style))
        
        warning_font_style = [self.config['warning_font'], self.config['warning_font_size']]
        if self.config['warning_italic']:
            warning_font_style.append('italic')
        self.text_widget.tag_config("warning",
                                   foreground=self.config['warning_color'],
                                   font=tuple(warning_font_style))
        self.text_widget.tag_config(
            "dictionary_lookup_match",
            background=self.config['translation_color'],
            foreground=bg_color
        )

        if dictionary_frame is not None:
            self.dictionary_text = tk.Text(
                dictionary_frame,
                bg=bg_color,
                fg=self.config['dictionary_meta_color'],
                font=(self.config['dictionary_meta_font'], self.config['dictionary_meta_font_size']),
                wrap=tk.WORD,
                borderwidth=0,
                highlightthickness=0,
                state='disabled',
                cursor="arrow"
            )
            dictionary_scrollbar = tk.Scrollbar(dictionary_frame, orient=tk.VERTICAL, command=self.dictionary_text.yview)
            self.dictionary_text.configure(yscrollcommand=dictionary_scrollbar.set)
            dictionary_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            self.dictionary_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.dictionary_text.tag_config(
                "heading",
                foreground=self.config['translation_color'],
                font=(self.config['translation_font'], 17, 'bold')
            )
            self.dictionary_text.tag_config(
                "headword",
                foreground=self.config['dictionary_entry_color'],
                font=(self.config['dictionary_entry_font'], self.config['dictionary_entry_font_size'], 'bold')
            )
            self.dictionary_text.tag_config(
                "definition",
                foreground=self.config['dictionary_definition_color'],
                font=(self.config['dictionary_definition_font'], self.config['dictionary_definition_font_size'], 'bold')
            )
            self.dictionary_text.tag_config(
                "meta",
                foreground=self.config['dictionary_meta_color'],
                font=(self.config['dictionary_meta_font'], self.config['dictionary_meta_font_size'])
            )
            self.dictionary_text.tag_config(
                "example_jp",
                foreground=self.config['dictionary_example_jp_color'],
                font=(self.config['dictionary_example_jp_font'], self.config['dictionary_example_jp_font_size'])
            )
            self.dictionary_text.tag_config(
                "example_en",
                foreground=self.config['dictionary_example_en_color'],
                font=(self.config['dictionary_example_en_font'], self.config['dictionary_example_en_font_size'])
            )
        else:
            self.dictionary_text = None

        resize_grip = tk.Label(self.overlay, text="◢", bg=bg_color,
                             fg=self.config['border_color'],
                             font=("Arial", 10), cursor="size_nw_se")
        resize_grip.place(relx=1.0, rely=1.0, anchor="se")
        resize_grip.bind("<Button-1>", self.start_resize)
        resize_grip.bind("<B1-Motion>", self.do_resize)

    def start_move(self, event):
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y

    def hide_overlay(self, event=None):
        if not self.overlay:
            return
        try:
            self.capture_overlay_geometry()
            self.flush_save_config()
        except Exception:
            pass
        try:
            self.overlay.withdraw()
        except Exception:
            pass

    def do_move(self, event):
        deltax = event.x - self.drag_data["x"]
        deltay = event.y - self.drag_data["y"]
        x = self.overlay.winfo_x() + deltax
        y = self.overlay.winfo_y() + deltay
        self.overlay.geometry(f"+{x}+{y}")

    def start_resize(self, event):
        self.drag_data["width"] = self.overlay.winfo_width()
        self.drag_data["height"] = self.overlay.winfo_height()
        self.drag_data["start_x"] = event.x_root
        self.drag_data["start_y"] = event.y_root

    def do_resize(self, event):
        delta_x = event.x_root - self.drag_data["start_x"]
        delta_y = event.y_root - self.drag_data["start_y"]
        
        new_width = max(self.config['min_width'],
                       min(self.config['max_width'],
                           self.drag_data["width"] + delta_x))
        new_width = max(new_width, self._get_effective_min_width())
        new_height = max(self.config['min_height'],
                        min(self.config['max_height'],
                            self.drag_data["height"] + delta_y))
        
        self.overlay.geometry(f"{new_width}x{new_height}")

    def on_overlay_configure(self, event):
        if event.widget != self.overlay:
            return
        try:
            self.capture_overlay_geometry()
            self.schedule_save_config()
        except Exception:
            pass

    def capture_overlay_geometry(self):
        if not self.overlay:
            return
        try:
            self.overlay.update_idletasks()
            self.config['window_x'] = self.overlay.winfo_x()
            self.config['window_y'] = self.overlay.winfo_y()
            self.config['default_width'] = self.overlay.winfo_width()
            self.config['default_height'] = self.overlay.winfo_height()
        except Exception:
            pass

    def schedule_save_config(self):
        if not self.overlay:
            self.save_config()
            return
        if self.save_after_id:
            try:
                self.overlay.after_cancel(self.save_after_id)
            except Exception:
                pass
        self.save_after_id = self.overlay.after(250, self.flush_save_config)

    def flush_save_config(self):
        self.save_after_id = None
        self.capture_overlay_geometry()
        self.save_config()

    def process_text(self, text: str) -> str:
        if not self.enabled:
            return text

        is_translator_enabled = self._is_translation_plugin_enabled()
        app = getattr(self, 'app', None)
        if app and self.overlay:
            app.run_on_ui_thread(self._display_processed_text, text, is_translator_enabled)

        return text

    def _display_processed_text(self, text, is_translator_enabled):
        if not self.overlay:
            return
        if self.overlay.state() == 'withdrawn':
            self.overlay.deiconify()
        self.update_text(text, is_translator_enabled)
        self._debug("process_text", overlay_state=self.overlay.state(), text_len=len(text), translator_enabled=is_translator_enabled)

    def process_clipboard_text(self, text: str):
        return text

    def _is_translation_plugin_enabled(self) -> bool:
        for module in list(sys.modules.values()):
            try:
                plugin = getattr(module, 'plugin', None)
                if plugin and getattr(plugin, 'enabled', False) and getattr(plugin, 'is_translation_plugin', False):
                    return True
            except Exception:
                pass
        return False

    def update_text(self, text, is_translator_enabled):
        if self.text_widget:
            self._debug("update_text", text_len=len(text), translator_enabled=is_translator_enabled)
            self.clear_dictionary_highlight()
            self.text_widget.config(state='normal')
            self.text_widget.delete(1.0, tk.END)
            
            if not is_translator_enabled:
                self.text_widget.insert(tk.END, "Please enable the translation plugin", "warning")
            else:
                clean_text = text.strip()
                parts = clean_text.split('\n')
                labeled_translation_pattern = re.compile(r'^\[([^\]]+)\]\s+(.*)$')

                translation_lines = []
                original_lines = []

                for line in parts:
                    match = labeled_translation_pattern.match(line)
                    if match:
                        plugin_name = match.group(1)
                        translated_text = match.group(2)
                        translation_lines.append(f"[{plugin_name}] {translated_text}")
                    else:
                        original_lines.append(line)

                if translation_lines:
                    for translation_line in translation_lines:
                        self.text_widget.insert(tk.END, translation_line + "\n", "translation")
                    if original_lines:
                        self.text_widget.insert(tk.END, "\n" + "\n".join(original_lines), "original")
                elif len(parts) >= 2:
                    translation = parts[-1]
                    original = '\n'.join(parts[:-1])
                    self.text_widget.insert(tk.END, translation + "\n", "translation")
                    self.text_widget.insert(tk.END, original, "original")
                else:
                    self.text_widget.insert(tk.END, clean_text, "original")
            
            self.text_widget.config(state='disabled')

    def init_dictionary_system(self):
        if not self.config.get('dictionary_enabled', True):
            return
        app = getattr(self, 'app', None)
        if app is None:
            self.set_dictionary_text("Dictionary unavailable: app context not attached.")
            self._debug("dictionary_unavailable", reason="app_context_missing")
            return

        dictionaries_root = self.get_runtime_dictionary_root()
        jitendex_dir = dictionaries_root / "jitendex"
        if not jitendex_dir.exists():
            self.set_dictionary_text(
                "No Jitendex dictionary was found.\n\n"
                f"Expected folder:\n{jitendex_dir}"
            )
            self._debug("dictionary_unavailable", reason="jitendex_missing", path=jitendex_dir)
            return

        cache_dir = Path(app.user_data_dir) / "dictionary_cache"
        self.dictionary_backend = JitendexDictionary(jitendex_dir, cache_dir)
        self.dictionary_backend.ensure_index_async()
        self._debug("dictionary_init", dictionary_dir=jitendex_dir, cache_dir=cache_dir)
        self.update_dictionary_status()

    def get_runtime_dictionary_root(self) -> Path:
        app = getattr(self, 'app', None)
        if app is not None:
            user_data_dir = getattr(app, 'user_data_dir', None)
            if user_data_dir:
                user_dictionary_root = Path(user_data_dir) / "dictionaries"
                if user_dictionary_root.exists():
                    return user_dictionary_root

            base_path = getattr(app, 'base_path', None)
            if base_path:
                bundled_dictionary_root = Path(base_path) / "dictionaries"
                if bundled_dictionary_root.exists():
                    return bundled_dictionary_root

        user_dictionary_root = get_runtime_user_data_path() / "dictionaries"
        if user_dictionary_root.exists():
            return user_dictionary_root
        return Path(__file__).resolve().parent.parent / "dictionaries"

    def update_dictionary_status(self):
        if not self.config.get('dictionary_enabled', True):
            return
        if self.overlay is None or self.dictionary_backend is None:
            return

        if self.dictionary_status_after_id:
            try:
                self.overlay.after_cancel(self.dictionary_status_after_id)
            except Exception:
                pass
            self.dictionary_status_after_id = None

        status = self.dictionary_backend.get_status()
        label_text = "Ready"
        label_color = self.config['translation_color']

        if status['error']:
            label_text = "Error"
            label_color = self.config['close_btn_color']
            self.set_dictionary_text(status['progress_message'])
        elif status['building']:
            current = status['progress_current']
            total = status['progress_total']
            label_text = f"Indexing {current}/{total}" if total else "Indexing"
            label_color = self.config['warning_color']
            current_text = self.get_dictionary_text().strip()
            if not current_text or current_text.startswith("Indexing Jitendex"):
                self.set_dictionary_text(status['progress_message'])
        elif status['ready']:
            entry_count = status['entry_count']
            label_text = f"Ready ({entry_count:,})" if entry_count else "Ready"
            label_color = self.config['translation_color']
            current_text = self.get_dictionary_text().strip()
            if not current_text or current_text.startswith("Indexing Jitendex") or current_text.startswith("Waiting to initialize"):
                self.set_dictionary_text("Dictionary ready. Click Japanese text in the overlay to look up terms.")
        else:
            label_text = "Initializing"
            label_color = self.config['original_color']

        status_snapshot = (label_text, bool(status['ready']), bool(status['building']), bool(status['error']))
        if status_snapshot != self._last_dictionary_status_log:
            self._last_dictionary_status_log = status_snapshot
            self._debug("dictionary_status", label=label_text, ready=status['ready'], building=status['building'], error=bool(status['error']))

        self.dictionary_status_after_id = self.overlay.after(1000, self.update_dictionary_status)

    def set_dictionary_text(self, text, tagged_sections=None):
        if self.dictionary_text is None:
            return
        self.dictionary_text.config(state='normal')
        self.dictionary_text.delete('1.0', tk.END)
        if tagged_sections:
            for section_text, tag in tagged_sections:
                if tag:
                    self.dictionary_text.insert(tk.END, section_text, tag)
                else:
                    self.dictionary_text.insert(tk.END, section_text)
        else:
            self.dictionary_text.insert(tk.END, text)
        self.dictionary_text.see('1.0')
        self.dictionary_text.config(state='disabled')

    def get_dictionary_text(self):
        if self.dictionary_text is None:
            return ""
        return self.dictionary_text.get('1.0', tk.END)

    def clear_dictionary_highlight(self):
        if self.text_widget is None:
            return
        self.text_widget.tag_remove('dictionary_lookup_match', '1.0', tk.END)
        self.text_widget.tag_remove(tk.SEL, '1.0', tk.END)

    def on_text_single_click(self, event):
        if self.overlay is None:
            return
        x, y = event.x, event.y
        self.overlay.after(0, lambda: self.lookup_text_at_coords(x, y, select_match=False))

    def on_text_double_click(self, event):
        if self.overlay is None:
            return
        x, y = event.x, event.y
        self.overlay.after(0, lambda: self.lookup_text_at_coords(x, y, select_match=True))

    def lookup_text_at_coords(self, x, y, select_match=False):
        if self.dictionary_backend is None or self.text_widget is None:
            return

        status = self.dictionary_backend.get_status()
        if status['error']:
            self.set_dictionary_text(status['progress_message'])
            return
        if not status['ready']:
            self.set_dictionary_text(status['progress_message'] or "Indexing Jitendex...")
            return

        try:
            click_index = self.text_widget.index(f"@{x},{y}")
            click_offset = int(self.text_widget.count("1.0", click_index, "chars")[0])
            full_text = self.text_widget.get("1.0", "end-1c")
        except Exception:
            self._debug("lookup_failed", reason="index_resolution_failed")
            return

        run_details = self.extract_lookup_run(full_text, click_offset)
        if run_details is None:
            self.clear_dictionary_highlight()
            self.set_dictionary_text("No Japanese term found near that click.")
            self._debug("lookup_no_run", x=x, y=y)
            return

        run_start, run_text, local_offset = run_details
        lookup_result = self.dictionary_backend.lookup_run_covering_offset(run_text, local_offset)
        if lookup_result is None:
            self.clear_dictionary_highlight()
            self.set_dictionary_text(f"No dictionary match found for:\n{run_text}")
            self._debug("lookup_no_match", run_text=run_text[:80])
            return

        match_start = run_start + lookup_result['match_start']
        match_end = run_start + lookup_result['match_end']
        self.highlight_dictionary_match(match_start, match_end, select_match=select_match)
        matches = lookup_result.get('matches') or [{
            "matched_text": lookup_result['matched_text'],
            "dictionary_form": lookup_result['matched_text'],
            "entries": lookup_result['entries'],
            "is_exact": True,
            "cost": 0,
            "reasons": [],
        }]
        self.render_dictionary_matches(matches)
        self._debug("lookup_match", matched_text=lookup_result['matched_text'], match_count=len(matches), entry_count=len(lookup_result['entries']))

    def extract_lookup_run(self, text, click_offset):
        if not text:
            return None

        offset = max(0, min(click_offset, len(text) - 1))
        while offset < len(text) and not self.dictionary_lookup_char_pattern.match(text[offset]):
            if text[offset] == '\n':
                return None
            offset += 1
            if offset - click_offset > 12:
                return None

        if offset >= len(text) or not self.dictionary_lookup_char_pattern.match(text[offset]):
            return None

        start = offset
        while start > 0 and self.dictionary_lookup_char_pattern.match(text[start - 1]):
            start -= 1

        end = offset + 1
        while end < len(text) and self.dictionary_lookup_char_pattern.match(text[end]):
            end += 1

        return start, text[start:end], offset - start

    def highlight_dictionary_match(self, match_start, match_end, select_match=False):
        if self.text_widget is None:
            return
        self.clear_dictionary_highlight()
        start_index = self.text_widget.index(f"1.0+{match_start}c")
        end_index = self.text_widget.index(f"1.0+{match_end}c")
        self.text_widget.tag_add('dictionary_lookup_match', start_index, end_index)
        if select_match:
            self.text_widget.tag_add(tk.SEL, start_index, end_index)
            self.text_widget.mark_set(tk.INSERT, end_index)
        self.text_widget.see(start_index)

    def render_dictionary_matches(self, matches):
        sections = []
        for match_index, match in enumerate(matches[:3], start=1):
            matched_text = match.get('matched_text', '')
            for entry_index, entry in enumerate(match.get('entries', [])[:3], start=1):
                reading = entry.get('reading', '').strip()
                tags = entry.get('term_tags', '').strip()
                display_tags_raw = entry.get('display_tags', '[]')
                rules = entry.get('rules', '').strip()
                summary = entry.get('summary_text', '').strip() or "(No summary text available)"
                header = entry.get('expression', matched_text)
                if reading and reading != header:
                    header = f"{header} [{reading}]"

                try:
                    display_tags = json.loads(display_tags_raw) if display_tags_raw else []
                except Exception:
                    display_tags = []
                try:
                    definitions = json.loads(entry.get('definitions_json', 'null'))
                except Exception:
                    definitions = None
                glossary_items, examples = extract_entry_glossaries_and_examples(definitions)
                combined_tags = []
                for tag_value in [tags, *display_tags]:
                    tag_value = str(tag_value).strip()
                    if tag_value and tag_value not in combined_tags:
                        combined_tags.append(tag_value)

                sections.append((f"{entry_index}. {header}\n", "headword"))
                if combined_tags:
                    sections.append((f"{', '.join(combined_tags)}\n", "meta"))
                if glossary_items:
                    for glossary in glossary_items[:6]:
                        cleaned_glossary = glossary.lstrip()
                        if cleaned_glossary.startswith("- "):
                            cleaned_glossary = cleaned_glossary[2:].lstrip()
                        sections.append((f"• {cleaned_glossary}\n", "definition"))
                else:
                    sections.append((f"{summary}\n", "definition"))
                if examples:
                    sections.append(("\n", None))
                    for jp, en in examples[:2]:
                        if jp:
                            sections.append((f"{jp}\n", "example_jp"))
                        if en:
                            sections.append((f"{en}\n", "example_en"))
                        sections.append(("\n", None))
                else:
                    sections.append(("\n", None))

            if match_index < min(len(matches), 3):
                sections.append(("────────────────\n\n", None))

        self.set_dictionary_text("", tagged_sections=sections)

    def get_settings(self) -> dict:
        if tkfont is not None:
            try:
                available_fonts = sorted(list(tkfont.families()))
            except Exception:
                available_fonts = []
        else:
            available_fonts = []

        if not available_fonts:
            available_fonts = ['Segoe UI', 'Arial', 'Tahoma', 'MS Gothic']

        fonts_dict = {font: font for font in available_fonts}
        
        color_presets = {
            '#1e1e2e': 'Dark Blue (Catppuccin)',
            '#282828': 'Dark Gray (Gruvbox)',
            '#000000': 'Black',
            '#1a1a1a': 'Dark Charcoal',
            '#0d1117': 'GitHub Dark',
            '#1c1c1c': 'Almost Black',
            '#2b2b2b': 'Dark Gray',
            '#ffffff': 'White',
            '#f5f5f5': 'Off White',
            '#e0e0e0': 'Light Gray',
            '#89b4fa': 'Blue (Catppuccin)',
            '#cdd6f4': 'Light Text (Catppuccin)',
            '#a6adc8': 'Dim Text (Catppuccin)',
            '#f38ba8': 'Pink (Catppuccin)',
            '#f9e2af': 'Yellow (Catppuccin)',
            '#a6e3a1': 'Green (Catppuccin)',
            '#fab387': 'Orange (Catppuccin)',
            '#f5c2e7': 'Light Pink',
            '#b4befe': 'Lavender',
            '#585b70': 'Border Gray',
            '#00ff00': 'Bright Green',
            '#ff0000': 'Red',
            '#ffff00': 'Yellow',
            '#00ffff': 'Cyan',
            '#ff00ff': 'Magenta',
        }
        
        return {
            'bg_color': (self.config['bg_color'], 'color', 'Background Color', color_presets),
            'window_opacity': (self.config['window_opacity'], 'int_slider', 'Window Opacity (%)', {'min': 10, 'max': 100}),
            'close_btn_color': (self.config['close_btn_color'], 'color', 'Close Button Color', color_presets),
            'border_color': (self.config['border_color'], 'color', 'Border/Grip Color', color_presets),
            'translation_font': (self.config['translation_font'], 'choice', 'Translation Font', fonts_dict),
            'translation_font_size': (self.config['translation_font_size'], 'int_slider', 'Translation Font Size', {'min': 8, 'max': 32}),
            'translation_bold': (self.config['translation_bold'], 'bool', 'Translation Bold', None),
            'translation_color': (self.config['translation_color'], 'color', 'Translation Text Color', color_presets),
            'original_font': (self.config['original_font'], 'choice', 'Original Text Font', fonts_dict),
            'original_font_size': (self.config['original_font_size'], 'int_slider', 'Original Text Font Size', {'min': 8, 'max': 32}),
            'original_color': (self.config['original_color'], 'color', 'Original Text Color', color_presets),
            'warning_font': (self.config['warning_font'], 'choice', 'Warning Font', fonts_dict),
            'warning_font_size': (self.config['warning_font_size'], 'int_slider', 'Warning Font Size', {'min': 8, 'max': 32}),
            'warning_italic': (self.config['warning_italic'], 'bool', 'Warning Italic', None),
            'warning_color': (self.config['warning_color'], 'color', 'Warning Text Color', color_presets),
            'min_width': (self.config['min_width'], 'int', 'Minimum Width (px)', None),
            'max_width': (self.config['max_width'], 'int', 'Maximum Width (px)', None),
            'min_height': (self.config['min_height'], 'int', 'Minimum Height (px)', None),
            'max_height': (self.config['max_height'], 'int', 'Maximum Height (px)', None),
            'default_width': (self.config['default_width'], 'int', 'Default Width (px)', None),
            'default_height': (self.config['default_height'], 'int', 'Default Height (px)', None),
            'dictionary_enabled': (self.config['dictionary_enabled'], 'bool', 'Enable Dictionary Pane', None),
            'dictionary_width': (self.config['dictionary_width'], 'int_slider', 'Dictionary Width (px)', {'min': 220, 'max': 900}),
            'dictionary_entry_font': (self.config['dictionary_entry_font'], 'choice', 'Dictionary Headword Font', fonts_dict),
            'dictionary_entry_font_size': (self.config['dictionary_entry_font_size'], 'int_slider', 'Dictionary Headword Font Size', {'min': 8, 'max': 36}),
            'dictionary_entry_color': (self.config['dictionary_entry_color'], 'color', 'Dictionary Headword Color', color_presets),
            'dictionary_definition_font': (self.config['dictionary_definition_font'], 'choice', 'Dictionary Definition Font', fonts_dict),
            'dictionary_definition_font_size': (self.config['dictionary_definition_font_size'], 'int_slider', 'Dictionary Definition Font Size', {'min': 8, 'max': 36}),
            'dictionary_definition_color': (self.config['dictionary_definition_color'], 'color', 'Dictionary Definition Color', color_presets),
            'dictionary_meta_font': (self.config['dictionary_meta_font'], 'choice', 'Dictionary Meta Font', fonts_dict),
            'dictionary_meta_font_size': (self.config['dictionary_meta_font_size'], 'int_slider', 'Dictionary Meta Font Size', {'min': 8, 'max': 28}),
            'dictionary_meta_color': (self.config['dictionary_meta_color'], 'color', 'Dictionary Meta Color', color_presets),
            'dictionary_example_jp_font': (self.config['dictionary_example_jp_font'], 'choice', 'Dictionary JP Example Font', fonts_dict),
            'dictionary_example_jp_font_size': (self.config['dictionary_example_jp_font_size'], 'int_slider', 'Dictionary JP Example Font Size', {'min': 8, 'max': 32}),
            'dictionary_example_jp_color': (self.config['dictionary_example_jp_color'], 'color', 'Dictionary JP Example Color', color_presets),
            'dictionary_example_en_font': (self.config['dictionary_example_en_font'], 'choice', 'Dictionary EN Example Font', fonts_dict),
            'dictionary_example_en_font_size': (self.config['dictionary_example_en_font_size'], 'int_slider', 'Dictionary EN Example Font Size', {'min': 8, 'max': 32}),
            'dictionary_example_en_color': (self.config['dictionary_example_en_color'], 'color', 'Dictionary EN Example Color', color_presets),
        }

    def set_setting(self, name: str, value) -> bool:
        if name in self.config:
            previous_value = self.config[name]
            self.config[name] = value
            if not self.save_config():
                self.config[name] = previous_value
                return False
            if self.overlay and self.enabled:
                self.on_disable()
                self.on_enable()
            return True
        return False

plugin = OverlayWindowPlugin()
