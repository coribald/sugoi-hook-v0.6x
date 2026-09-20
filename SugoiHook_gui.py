#!/usr/bin/env python3
"""
SugoiHook GUI - Modern Text Extraction Interface
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import subprocess
import threading
import psutil
import os
import re
import sys
import time
import importlib.util
import json
import hashlib
import logging
import traceback
from collections import deque
from pathlib import Path

from output_pipeline import OutputPipeline

ORIGINAL_STDOUT = sys.stdout
ORIGINAL_STDERR = sys.stderr
EARLY_LOG_STREAM = None
EARLY_LOG_PATH = None


def get_runtime_launcher_path() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve()

    argv0 = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None
    executable = Path(sys.executable).resolve()

    if argv0 and argv0.suffix.lower() == '.exe' and argv0 != executable:
        return argv0

    if executable.suffix.lower() == '.exe' and 'python' not in executable.name.lower():
        return executable

    return Path(__file__).resolve()


def get_runtime_bundle_base_path() -> Path:
    if getattr(sys, 'frozen', False) or getattr(sys, '__compiled__', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_runtime_user_data_path() -> Path:
    return get_runtime_launcher_path().parent


def runtime_debug_logging_enabled() -> bool:
    env_enabled = os.environ.get('SUGOIHOOK_DEBUG_LOGGING', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    argv_enabled = any(str(arg).strip().lower() == '--debug' for arg in sys.argv[1:])
    executable_name = Path(sys.executable).name.lower()
    argv0_name = Path(sys.argv[0]).name.lower() if sys.argv else ''
    debug_build_enabled = any(
        name.endswith('_debug.exe') or name.endswith('debug.exe')
        for name in (executable_name, argv0_name)
        if name
    )
    return env_enabled or argv_enabled or debug_build_enabled


def bootstrap_runtime_streams():
    global EARLY_LOG_STREAM, EARLY_LOG_PATH

    try:
        EARLY_LOG_PATH = get_runtime_user_data_path() / 'sugoihook-runtime.log'
        EARLY_LOG_STREAM = open(EARLY_LOG_PATH, 'a', encoding='utf-8', buffering=1)
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        EARLY_LOG_STREAM.write(f"\n===== Sugoi Hook bootstrap started {timestamp} =====\n")
        sys.stdout = EARLY_LOG_STREAM
        sys.stderr = EARLY_LOG_STREAM
        return EARLY_LOG_PATH
    except Exception:
        return None


bootstrap_runtime_streams()

from PIL import Image, ImageTk, ImageDraw
import win32gui
import win32ui
import win32con
import win32process
import ctypes

try:
    import pystray
    from pystray import MenuItem as item
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

try:
    from plugins import HookPlugin
    PLUGINS_AVAILABLE = True
except ImportError:
    PLUGINS_AVAILABLE = False

# Constants
CREATE_NO_WINDOW = 0x08000000
DEFAULT_DPI = 96.0
MIN_SYSTEM_PID = 100
ICON_SIZE = 32
SCALED_ICON_SIZE = 24
ICON_CORNER_RADIUS = 3
MAX_HOOK_TEXTS = 3
MAX_PREVIEW_LENGTH = 80
AUTO_HOOK_INITIAL_DELAY = 8000
AUTO_HOOK_RETRY_DELAY = 5000
AUTO_HOOK_MAX_RETRIES = 3
PROCESS_MONITOR_DELAY = 3000
GAME_LAUNCH_ATTACH_DELAY = 4000


def get_runtime_base_path() -> Path:
    return get_runtime_bundle_base_path()


class StreamTee:
    def __init__(self, *streams):
        self.streams = [stream for stream in streams if stream is not None]

    def write(self, data):
        for stream in self.streams:
            try:
                stream.write(data)
                stream.flush()
            except Exception:
                pass
        return len(data)

    def flush(self):
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass

    def isatty(self):
        return False


def setup_runtime_logging():
    try:
        log_path = get_runtime_user_data_path() / 'sugoihook-runtime.log'
        log_stream = open(log_path, 'a', encoding='utf-8', buffering=1)
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        log_stream.write(f"\n===== Sugoi Hook session started {timestamp} =====\n")

        original_stdout = ORIGINAL_STDOUT
        original_stderr = ORIGINAL_STDERR
        sys.stdout = StreamTee(original_stdout, log_stream)
        sys.stderr = StreamTee(original_stderr, log_stream)

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[logging.FileHandler(log_path, encoding='utf-8')],
            force=True,
        )

        def log_uncaught_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                if original_stderr:
                    original_stderr.write('KeyboardInterrupt\n')
                    original_stderr.flush()
                return
            logging.critical(
                'Uncaught exception',
                exc_info=(exc_type, exc_value, exc_traceback),
            )

        sys.excepthook = log_uncaught_exception

        if hasattr(threading, 'excepthook'):
            def thread_exception_handler(args):
                logging.critical(
                    'Unhandled thread exception in %s',
                    getattr(args.thread, 'name', 'unknown'),
                    exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
                )
            threading.excepthook = thread_exception_handler

        logging.info('Runtime logging initialized at %s', log_path)
        return log_path
    except Exception:
        traceback.print_exc()
        return None
class SugoiHookGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("SugoiHook v0.6x")
        self.root.geometry("1000x750")
        self.root.minsize(900, 650)
        
        # Color schemes for light/dark mode
        self.dark_colors = {
            'bg': '#1e1e2e',
            'fg': '#cdd6f4',
            'primary': "#a09dfb",
            'secondary': '#f38ba8',
            'success': '#a6e3a1',
            'warning': '#f9e2af',
            'surface': '#313244',
            'surface_light': '#45475a',
            'border': '#585b70',
            'text': '#cdd6f4',
            'text_dim': '#9399b2',
            'accent': '#b4befe'
        }
        
        self.light_colors = {
            'bg': '#eff1f5',
            'fg': '#4c4f69',
            'primary': '#a09dfb',
            'secondary': '#d20f39',
            'success': '#40a02b',
            'warning': '#df8e1d',
            'surface': '#e6e9ef',
            'surface_light': '#ccd0da',
            'border': '#9ca0b0',
            'text': '#4c4f69',
            'text_dim': '#6c6f85',
            'accent': '#7287fd'
        }
        
        # Current theme - dark mode is default
        self.colors = self.dark_colors.copy()
        
        # Calculate DPI scale factor
        try:
            dpi = self.root.winfo_fpixels('1i')
            self.scale_factor = dpi / DEFAULT_DPI
        except Exception:
            self.scale_factor = 1.0
        
        # Apply scaling to window size
        width = int(1000 * self.scale_factor)
        height = int(750 * self.scale_factor)
        self.root.geometry(f"{width}x{height}")
        
        min_width = int(900 * self.scale_factor)
        min_height = int(650 * self.scale_factor)
        self.root.minsize(min_width, min_height)
        
        # State variables
        self.cli_process = None
        self.attached_pid = None
        self.hooks = {}
        self.hooks_lock = threading.Lock()
        self.hook_event_sequence = 0
        self.selected_hook_id = None
        self.is_reading = False
        self.process_icons = {}
        self.is_fullscreen = False
        
        # Plugin system
        self.plugins = {}
        self.active_plugins = []
        self.plugin_order = []
        self.plugins_config_path = None
        self.plugins_folder = None
        self.bundled_plugins_folder = None
        self.plugin_file_paths = {}
        self.plugin_settings = {}
        
        # Game profiles system
        self.game_profiles = {}
        self.game_profiles_path = None
        self.current_game_id = None
        self.auto_hook_pending = False
        self.auto_hook_data = None
        self.silent_auto_launch = False
        
        # Auto-copy settings
        self.auto_copy_enabled = tk.BooleanVar(value=True)
        
        # Statistics tracking
        self.stats = {'lines': 0, 'words': 0, 'chars': 0, 'start_time': None, 'last_update': time.time()}
        self.status_notice_after_id = None
        self.status_notice_text = ""
        self.process_section_collapsed = False
        self.hook_section_collapsed = False
        self.plugins_section_collapsed = True
        self.output_section_collapsed = False
        self.events_section_collapsed = False
        self.extracted_section_collapsed = False
        self.window_geometry = None
        self.compact_window_geometry = None
        self.window_geometry_after_id = None
        self.pipeline_debug_enabled = runtime_debug_logging_enabled()
        self.output_processing_lock = threading.RLock()
        self.ui_callback_lock = threading.Lock()
        self.ui_callback_queue = deque()
        self.ui_callback_shutdown = False
        self.root.after(10, self.drain_ui_callbacks)
        self.output_pipeline = OutputPipeline(
            prepare=self.prepare_plugin_output_bundle,
            complete=self.complete_plugin_output_bundle,
            deliver=self.deliver_plugin_output_bundle,
            is_latest_only=self.prepared_output_requires_translation,
            on_error=self.handle_output_pipeline_error,
            on_stale=self.handle_stale_output_bundle,
            on_superseded=self.handle_superseded_output_bundle,
        )
        
        # System tray
        self.tray_icon = None
        self.is_minimized_to_tray = False
        self.shutdown_started = False
        
        # System directories to check for filtering
        self.system_dirs = [
            'c:\\windows\\system32',
            'c:\\windows\\syswow64',
            'c:\\windows\\systemapps',
            'c:\\windows\\winsxs',
            'c:\\program files\\windows',
            'c:\\program files (x86)\\windows',
            'c:\\program files\\windowsapps',
            'c:\\program files (x86)\\windowsapps',
        ]
        
        # Known system process patterns (case-insensitive)
        self.system_process_patterns = [
            'svchost', 'dllhost', 'conhost', 'runtimebroker', 'taskhostw',
            'sihost', 'csrss', 'smss', 'wininit', 'services', 'lsass',
            'winlogon', 'fontdrvhost', 'dwm', 'audiodg', 'spoolsv',
            'searchindexer', 'searchhost', 'searchprotocolhost', 'searchfilterhost',
            'startmenuexperiencehost', 'shellexperiencehost', 'textinputhost',
            'securityhealthservice', 'securityhealthsystray', 'smartscreen',
            'applicationframehost', 'systemsettings', 'lockapp', 'winstore.app',
            'microsoftedge', 'msedge', 'identity helper', 'crashpad_handler',
        ]
        
        # Known bloatware/utility patterns
        self.bloatware_patterns = [
            'nvidia', 'amd', 'intel', 'realtek', 'asus', 'msi', 'gigabyte',
            'corsair', 'razer', 'logitech', 'steelseries', 'creative',
            'onedrive', 'dropbox', 'googledrive', 'icloud', 'backup',
            'antivirus', 'defender', 'malwarebytes', 'avast', 'avg', 'norton',
            'mcafee', 'kaspersky', 'bitdefender', 'eset', 'sophos',
            'chrome', 'firefox', 'edge', 'opera', 'brave', 'vivaldi', 'safari',
            'discord', 'slack', 'teams', 'zoom', 'skype', 'telegram', 'whatsapp',
            'spotify', 'itunes', 'vlc', 'winamp', 'foobar', 'musicbee',
            'steam', 'epic', 'origin', 'uplay', 'battlenet', 'gog', 'riot',
            'vanguard', 'easyanticheat', 'battleye', 'gameguard',
            'obs', 'streamlabs', 'xsplit', 'nvidia share', 'amd link',
            'notepad++', 'sublime', 'atom', 'brackets', 'code', 'vscode',
            'pycharm', 'intellij', 'eclipse', 'netbeans', 'visual studio',
            'winrar', '7zip', 'winzip', 'peazip', 'bandizip',
            'ccleaner', 'defraggler', 'recuva', 'speccy', 'hwmonitor',
            'cpuz', 'gpuz', 'hwinfo', 'crystaldisk', 'msiafterburner',
            'python', 'java', 'node', 'ruby', 'php', 'perl', 'go',
            'powershell', 'cmd', 'terminal', 'git', 'svn', 'tortoise',
        ]
        
        # Specific executables to always exclude
        self.excluded_executables = {
            'system', 'registry', 'idle', 'system idle process',
            'explorer.exe', 'taskmgr.exe', 'ctfmon.exe',
            'winword.exe', 'excel.exe', 'powerpnt.exe', 'outlook.exe',
            'acrobat.exe', 'acrord32.exe', 'foxit reader.exe',
            'notepad.exe', 'mspaint.exe', 'calc.exe', 'snippingtool.exe',
            'sugoi_hook.exe'
        }
        
        # Determine CLI paths - handle both development and compiled modes
        launcher_path = get_runtime_launcher_path()
        is_frozen = getattr(sys, 'frozen', False)
        is_nuitka = getattr(sys, '__compiled__', False) or (
            launcher_path.suffix.lower() == '.exe' and
            launcher_path.resolve() != Path(__file__).resolve()
        )
        is_compiled = is_frozen or is_nuitka
        
        # Set base paths based on compilation mode
        if is_compiled:
            self.base_path = Path(sys._MEIPASS) if is_frozen else get_runtime_bundle_base_path()
            self.app_path = get_runtime_user_data_path()
            self.user_data_dir = self.app_path
            self.user_data_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.base_path = self.app_path = Path(__file__).parent
            self.user_data_dir = self.app_path
        
        # Configure plugin and profile paths
        self.bundled_plugins_folder = self.base_path / "plugins"
        self.plugins_folder = self.user_data_dir / "plugins"
        self.plugins_config_path = self.user_data_dir / "plugins_config.json"
        self.game_profiles_path = self.user_data_dir / "game_profiles.json"
        
        # Engine executable paths
        self.luna_x86_path = self.base_path / "luna_builds" / "LunaHostCLI32.exe"
        self.luna_x64_path = self.base_path / "luna_builds" / "LunaHostCLI64.exe"
        self.logo_path = self.base_path / "logo.webp"
        
        # Luna-only build
        self.current_engine = "luna"
        
        # Initialize plugin system
        self.init_plugin_system()
        self.apply_saved_window_geometry()
        
        # Check that Luna CLI executables exist
        luna_exists = self.luna_x86_path.exists() or self.luna_x64_path.exists()
        
        if not luna_exists:
            messagebox.showerror("Error", 
                "No Luna hook engine executables found!\n\n"
                "Expected locations:\n"
                f"Luna: {self.luna_x86_path} or {self.luna_x64_path}")
            sys.exit(1)
        
        self.setup_modern_theme()
        self.set_window_icon()
        self.create_status_bar()
        self.setup_ui()
        self.setup_system_tray()
        self.refresh_processes()
        self.update_status_bar()
        
        # Bind fullscreen detection
        self.root.bind('<F11>', self.toggle_fullscreen)
        self.root.bind('<Escape>', self.exit_fullscreen)
        self.root.bind('<Configure>', self.on_window_configure)
        

    def scale(self, value):
        """Scale a value based on DPI"""
        return int(value * self.scale_factor)

    def run_on_ui_thread(self, callback, *args):
        """Run a callback on the Tk UI thread."""
        if threading.current_thread() is threading.main_thread():
            callback(*args)
            return
        with self.ui_callback_lock:
            if not self.ui_callback_shutdown:
                self.ui_callback_queue.append((callback, args))

    def drain_ui_callbacks(self):
        """Run callbacks queued by background workers without calling Tk off-thread."""
        callbacks = []
        with self.ui_callback_lock:
            while self.ui_callback_queue:
                callbacks.append(self.ui_callback_queue.popleft())
            shutdown = self.ui_callback_shutdown
        for callback, args in callbacks:
            try:
                callback(*args)
            except Exception:
                logging.exception("UI callback failed")
        if not shutdown:
            self.root.after(10, self.drain_ui_callbacks)

    # ==================== PLUGIN SYSTEM METHODS =============    
    def init_plugin_system(self):
        """Initialize the plugin system"""
        # Ensure writable custom plugins folder exists regardless of bundled plugin layout
        if not self.plugins_folder.exists():
            self.plugins_folder.mkdir(parents=True, exist_ok=True)
            
        if not PLUGINS_AVAILABLE:
            return
        
        # Load saved plugin configuration
        self.load_plugins_config()
        
        # Discover and load available plugins
        self.discover_plugins()
    
    def discover_plugins(self):
        """Discover all available plugins in the plugins folder"""
        plugin_search_paths = []
        if self.bundled_plugins_folder and self.bundled_plugins_folder.exists():
            plugin_search_paths.append(self.bundled_plugins_folder)
        if self.plugins_folder and self.plugins_folder.exists() and self.plugins_folder not in plugin_search_paths:
            plugin_search_paths.append(self.plugins_folder)

        if not plugin_search_paths:
            return
        
        current_files = set()
        for plugin_dir in plugin_search_paths:
            for plugin_file in plugin_dir.glob("*.py"):
                # Skip __init__.py and other special files
                if plugin_file.name.startswith("_"):
                    continue
                
                current_files.add(plugin_file.name)
                
                try:
                    if runtime_debug_logging_enabled():
                        logging.info('Discovering plugin file: %s', plugin_file)
                    plugin = self.load_plugin(plugin_file)
                    # Apply saved settings to the plugin
                    if plugin:
                        if runtime_debug_logging_enabled():
                            logging.info('Loaded plugin: %s (%s)', plugin_file.name, getattr(plugin, 'name', plugin_file.stem))
                    else:
                        logging.warning('Plugin returned no instance: %s', plugin_file.name)

                    if plugin and plugin_file.name in self.plugin_settings:
                        for setting_name, setting_value in self.plugin_settings[plugin_file.name].items():
                            try:
                                plugin.set_setting(setting_name, setting_value)
                            except Exception:
                                pass
                    
                    # If this plugin was previously active, enable it
                    if plugin and plugin_file.name in self.active_plugins:
                        plugin.enabled = True
                        plugin.on_enable()
                except Exception:
                    pass
        
        # Clean up active_plugins list - remove any that weren't found
        self.active_plugins = [p for p in self.active_plugins if p in self.plugins]
        self.plugin_file_paths = {
            filename: path for filename, path in self.plugin_file_paths.items()
            if filename in current_files
        }
        
        # Update plugin_order
        # 1. Remove files that no longer exist
        self.plugin_order = [p for p in self.plugin_order if p in self.plugins]
        # 2. Add new files that aren't in the order list yet
        for filename in self.plugins:
            if filename not in self.plugin_order:
                self.plugin_order.append(filename)
        
        # Save the updated configuration
        self.save_plugins_config()

    def load_plugins_config(self):
        """Load plugin configuration from JSON file"""
        self.active_plugins = []
        self.plugin_order = []
        self.plugin_settings = {}
        
        if self.plugins_config_path and self.plugins_config_path.exists():
            try:
                with open(self.plugins_config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.active_plugins = config.get('active_plugins', [])
                    self.plugin_order = config.get('plugin_order', [])
                    self.plugin_settings = config.get('plugin_settings', {})
                    self.window_geometry = config.get('window_geometry')
                    self.compact_window_geometry = config.get('compact_window_geometry')
            except Exception:
                pass
    
    def save_plugins_config(self):
        """Save plugin configuration to JSON file"""
        if self.plugins_config_path:
            try:
                # Ensure plugin_order reflects all known plugins if empty
                if not self.plugin_order:
                    self.plugin_order = sorted(list(self.plugins.keys()))
                
                config = {
                    'active_plugins': self.active_plugins,
                    'plugin_order': self.plugin_order,
                    'plugin_settings': self.plugin_settings,
                    'window_geometry': self.window_geometry,
                    'compact_window_geometry': self.compact_window_geometry,
                }
                
                # Ensure directory exists
                if not self.plugins_config_path.parent.exists():
                    self.plugins_config_path.parent.mkdir(parents=True, exist_ok=True)
                    
                with open(self.plugins_config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2)
            except Exception:
                pass

    def apply_saved_window_geometry(self):
        """Restore the last saved main window size and position."""
        if not self.window_geometry:
            return
        try:
            self.root.geometry(self.window_geometry)
        except Exception:
            pass

    def is_compact_window_layout(self):
        """Return True when the window is in the compact collapsed layout."""
        return self.process_section_collapsed and self.hook_section_collapsed and self.plugins_section_collapsed

    def schedule_window_geometry_save(self):
        """Debounce main window geometry persistence during drags/resizes."""
        if self.window_geometry_after_id:
            try:
                self.root.after_cancel(self.window_geometry_after_id)
            except Exception:
                pass
        self.window_geometry_after_id = self.root.after(250, self.persist_window_geometry)

    def persist_window_geometry(self):
        """Persist the current main window geometry when it is in a normal state."""
        self.window_geometry_after_id = None
        try:
            if self.is_fullscreen:
                return
            if self.root.state() != 'normal':
                return
            geometry = self.root.geometry()
            if not geometry:
                return

            changed = False
            if self.is_compact_window_layout():
                if geometry != self.compact_window_geometry:
                    self.compact_window_geometry = geometry
                    changed = True
            else:
                if geometry != self.window_geometry:
                    self.window_geometry = geometry
                    changed = True

            if changed:
                self.save_plugins_config()
        except Exception:
            pass

    def restore_compact_window_geometry(self):
        """Restore the last saved compact geometry when all top sections are collapsed."""
        if not self.is_compact_window_layout():
            return
        geometry = self.compact_window_geometry or self.window_geometry
        if not geometry:
            return
        try:
            if self.root.state() == 'normal' and self.root.geometry() != geometry:
                self.root.geometry(geometry)
                if hasattr(self, 'update_scrollbar_visibility'):
                    self.root.after(50, self.update_scrollbar_visibility)
        except Exception:
            pass

    def restore_full_window_geometry(self):
        """Restore the last saved expanded geometry when leaving compact mode."""
        geometry = self.window_geometry
        if not geometry:
            return
        try:
            if self.root.state() == 'normal' and self.root.geometry() != geometry:
                self.root.geometry(geometry)
                if hasattr(self, 'update_scrollbar_visibility'):
                    self.root.after(50, self.update_scrollbar_visibility)
        except Exception:
            pass

    def notify_user(self, message, level='info', timeout_ms=4000):
        """Show a lightweight in-app status notice instead of a modal dialog."""
        if not hasattr(self, 'status_notice_label'):
            return

        colors = {
            'info': self.colors['text_dim'],
            'success': self.colors['success'],
            'warning': self.colors['warning'],
            'error': self.colors['secondary'],
        }
        self.status_notice_text = message
        self.status_notice_label.config(
            text=message,
            foreground=colors.get(level, self.colors['text_dim'])
        )

        if self.status_notice_after_id:
            try:
                self.root.after_cancel(self.status_notice_after_id)
            except Exception:
                pass
            self.status_notice_after_id = None

        if timeout_ms:
            self.status_notice_after_id = self.root.after(timeout_ms, self.clear_notice)

    def clear_notice(self):
        """Clear the transient status notice."""
        self.status_notice_after_id = None
        self.status_notice_text = ""
        if hasattr(self, 'status_notice_label'):
            self.status_notice_label.config(text="Ready", foreground=self.colors['text_dim'])

    def get_selected_plugin_filename(self):
        """Return the filename for the currently selected plugin row."""
        if not hasattr(self, 'plugins_tree'):
            return None

        selection = self.plugins_tree.selection()
        if not selection:
            return None

        item = self.plugins_tree.item(selection[0])
        plugin_name = item['values'][1]

        for filename, plugin in self.plugins.items():
            if plugin.name == plugin_name:
                return filename

        return None

    def get_plugin_filename_by_name(self, plugin_name):
        """Return the filename for a plugin by its display name."""
        for filename, plugin in self.plugins.items():
            if plugin.name == plugin_name:
                return filename
        return None

    def get_hooks_snapshot(self):
        with self.hooks_lock:
            return {
                str(hook_id): dict(hook_info)
                for hook_id, hook_info in self.hooks.items()
            }

    def mark_hook_event_submitted(self, hook_id, event_sequence):
        with self.hooks_lock:
            hook_info = self.hooks.get(str(hook_id))
            if hook_info is not None:
                hook_info['last_pipeline_sequence'] = max(
                    int(hook_info.get('last_pipeline_sequence') or 0),
                    int(event_sequence),
                )

    def mark_hook_event_processed(self, hook_id, event_sequence):
        with self.hooks_lock:
            hook_info = self.hooks.get(str(hook_id))
            if hook_info is not None:
                hook_info['last_processed_sequence'] = max(
                    int(hook_info.get('last_processed_sequence') or 0),
                    int(event_sequence),
                )

    def get_hook_concatenation_state(self):
        """Return whether hook concatenation mode is active and which hooks it is using."""
        with self.output_processing_lock:
            return self._get_hook_concatenation_state_unlocked()

    def _get_hook_concatenation_state_unlocked(self):
        for plugin_filename, plugin in self.plugins.items():
            try:
                if getattr(plugin, 'name', '') != 'Hook Concatenation':
                    continue
                if plugin_filename not in self.active_plugins or not getattr(plugin, 'enabled', False):
                    break
                plugin_state = getattr(plugin, '_state', {})
                enabled_mode = bool(plugin_state.get('enabled_mode', False))
                if hasattr(plugin, '_get_concat_config'):
                    concat_config = plugin._get_concat_config()
                    dialogue_hook_id = str(concat_config.get('dialogue_hook_id', '')).strip()
                    prefix_hook_ids = [str(hook_id).strip() for hook_id in concat_config.get('prefix_hook_ids', []) if str(hook_id).strip()]
                    hook_ids = [hook_id for hook_id in prefix_hook_ids + ([dialogue_hook_id] if dialogue_hook_id else []) if hook_id]
                else:
                    dialogue_hook_id = str(plugin_state.get('dialogue_hook_id', '')).strip()
                    prefix_hook_ids = [hook_id.strip() for hook_id in str(plugin_state.get('prefix_hook_ids', '')).split(',') if hook_id.strip().isdigit()]
                    hook_ids = prefix_hook_ids + ([dialogue_hook_id] if dialogue_hook_id else [])
                    if not hook_ids:
                        raw_hook_ids = str(plugin_state.get('hook_ids', '')).strip()
                        hook_ids = [hook_id.strip() for hook_id in raw_hook_ids.split(',') if hook_id.strip().isdigit()]
                buffered_hooks = list(plugin_state.get('hook_buffers', {}).keys())
                return {
                    'active': enabled_mode and bool(hook_ids),
                    'hook_ids': hook_ids,
                    'buffered_hooks': buffered_hooks,
                    'dialogue_hook_id': dialogue_hook_id,
                    'prefix_hook_ids': prefix_hook_ids,
                    'speaker_wait_ms': int(plugin_state.get('speaker_wait_ms', 150)),
                }
            except Exception as exc:
                if runtime_debug_logging_enabled():
                    logging.exception("Failed to read Hook Concatenation state: %s", exc)
                break

        return {
            'active': False,
            'hook_ids': [],
            'buffered_hooks': [],
            'dialogue_hook_id': '',
            'prefix_hook_ids': [],
            'speaker_wait_ms': 150,
        }

    def format_hook_function_label(self, hook_id, function_name):
        """Decorate hook list rows when hook concatenation mode is using them."""
        concat_state = self.get_hook_concatenation_state()
        if concat_state['active'] and str(hook_id) in concat_state['hook_ids']:
            order_index = concat_state['hook_ids'].index(str(hook_id)) + 1
            total = len(concat_state['hook_ids'])
            return f"[Concat {order_index}/{total}] {function_name}"
        return function_name

    def refresh_hook_list_annotations(self):
        """Refresh hook list labels to reflect concatenation mode markers."""
        if not hasattr(self, 'hook_tree'):
            return

        for item in self.hook_tree.get_children():
            values = list(self.hook_tree.item(item).get('values', ()))
            if len(values) < 3:
                continue
            hook_id = str(values[0])
            function_name = self.hooks.get(hook_id, {}).get('function', values[1])
            preview = values[2]
            self.hook_tree.item(item, values=(hook_id, self.format_hook_function_label(hook_id, function_name), preview))

    def update_hook_status_panel(self, message=None):
        """Refresh the hook state summary labels."""
        if not hasattr(self, 'hook_status_summary'):
            return

        concat_state = self.get_hook_concatenation_state()
        self.refresh_hook_list_annotations()

        if self.attached_pid:
            process_text = f"Attached PID: {self.attached_pid}"
        else:
            process_text = "Not attached"

        engine_text = "Engine: Luna"
        self.hook_status_summary.config(
            text=f"{process_text} | {engine_text}",
            foreground=self.colors['success'] if self.attached_pid else self.colors['text_dim']
        )

        if concat_state['active']:
            hooks_text = ', '.join(concat_state['hook_ids'])
            self.hook_active_label.config(
                text=f"Current source: Hook Concatenation (prefix: {', '.join(concat_state['prefix_hook_ids']) or 'none'} | dialogue: {concat_state['dialogue_hook_id'] or hooks_text})",
                foreground=self.colors['primary']
            )
        elif self.selected_hook_id:
            hook_info = self.hooks.get(self.selected_hook_id, {})
            function_name = hook_info.get('function', 'Unknown')
            self.hook_active_label.config(
                text=f"Current hook: ID {self.selected_hook_id} ({function_name})",
                foreground=self.colors['primary']
            )
        else:
            self.hook_active_label.config(
                text="Current hook: none selected",
                foreground=self.colors['text_dim']
            )

        if hasattr(self, 'hook_concat_label'):
            if concat_state['active']:
                buffered = [hook_id for hook_id in concat_state['hook_ids'] if hook_id in concat_state['buffered_hooks']]
                waiting = [hook_id for hook_id in concat_state['hook_ids'] if hook_id not in concat_state['buffered_hooks']]
                buffered_text = ', '.join(buffered) if buffered else 'none yet'
                waiting_text = ', '.join(waiting) if waiting else 'ready'
                self.hook_concat_label.config(
                    text=f"Concatenation: active | seen {buffered_text} | waiting {waiting_text} | grace {concat_state['speaker_wait_ms']}ms",
                    foreground=self.colors['accent'] if waiting else self.colors['success']
                )
            else:
                self.hook_concat_label.config(
                    text="Concatenation: inactive",
                    foreground=self.colors['text_dim']
                )

        profile_text = "Saved profile: none"
        profile_color = self.colors['text_dim']
        if self.current_game_id and self.current_game_id in self.game_profiles:
            profile = self.game_profiles[self.current_game_id]
            profile_text = f"Saved profile: {profile.get('hook_function', profile.get('hook_data', 'available'))}"
            profile_color = self.colors['accent']

        if self.auto_hook_pending:
            profile_text = "Saved profile: auto-hook pending"
            profile_color = self.colors['warning']

        self.hook_profile_label.config(text=profile_text, foreground=profile_color)

        if message:
            self.hook_last_action_label.config(text=f"Last action: {message}", foreground=self.colors['fg'])
        elif self.hook_last_action_label.cget('text') == "":
            self.hook_last_action_label.config(
                text="Last action: waiting for attachment",
                foreground=self.colors['text_dim']
            )
    
    def load_plugin(self, plugin_path):
        """Load a single plugin from a file path"""
        if not PLUGINS_AVAILABLE:
            return None
        
        plugin_name = plugin_path.stem
        
        try:
            # Load the module dynamically
            spec = importlib.util.spec_from_file_location(plugin_name, plugin_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[plugin_name] = module
            spec.loader.exec_module(module)
            
            # Look for a 'plugin' instance or a class that inherits from HookPlugin
            plugin_instance = None
            
            if hasattr(module, 'plugin'):
                plugin_instance = module.plugin
            else:
                # Look for a class that inherits from HookPlugin
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and 
                        issubclass(attr, HookPlugin) and 
                        attr is not HookPlugin):
                        plugin_instance = attr()
                        break
            
            if plugin_instance:
                try:
                    plugin_instance.app = self
                except Exception:
                    pass
                self.plugins[plugin_path.name] = plugin_instance
                self.plugin_file_paths[plugin_path.name] = plugin_path
                return plugin_instance
                
        except Exception:
            logging.exception('Failed to load plugin from %s', plugin_path)
            pass
        
        return None
    
    
    def activate_plugin(self, plugin_filename):
        """Activate a plugin"""
        with self.output_processing_lock:
            if plugin_filename in self.plugins and plugin_filename not in self.active_plugins:
                self.active_plugins.append(plugin_filename)
                plugin = self.plugins[plugin_filename]
                plugin.enabled = True
                plugin.on_enable()
                self.save_plugins_config()
                return True
        return False
    
    def deactivate_plugin(self, plugin_filename):
        """Deactivate a plugin"""
        with self.output_processing_lock:
            if plugin_filename in self.active_plugins:
                self.active_plugins.remove(plugin_filename)
                if plugin_filename in self.plugins:
                    plugin = self.plugins[plugin_filename]
                    plugin.enabled = False
                    plugin.on_disable()
                self.save_plugins_config()
                return True
        return False

    def _pipeline_preview(self, value, limit=180):
        """Return a compact one-line preview for pipeline logging."""
        if value is None:
            return "<None>"
        text = str(value).replace("\r", "\\r").replace("\n", "\\n")
        if len(text) > limit:
            return text[:limit] + "..."
        return text

    def log_pipeline(self, stage, **fields):
        """Emit focused pipeline diagnostics to the runtime log."""
        if not getattr(self, 'pipeline_debug_enabled', False):
            return
        try:
            parts = []
            for key, value in fields.items():
                if isinstance(value, str):
                    value = self._pipeline_preview(value)
                elif value is None:
                    value = '<None>'
                parts.append(f"{key}={value}")
            message = f"[PIPELINE] {stage}"
            if parts:
                message += " | " + " | ".join(parts)
            logging.info(message)
            try:
                print(message, flush=True)
            except Exception:
                pass
        except Exception:
            pass

    def shutdown_plugin_instances(self):
        """Run plugin teardown and clear dynamically loaded plugin modules."""
        plugin_filenames = list(self.plugins.keys())

        for plugin_filename in plugin_filenames:
            plugin = self.plugins.get(plugin_filename)
            if plugin is None:
                continue
            try:
                plugin.enabled = False
            except Exception:
                pass
            try:
                plugin.on_disable()
            except Exception:
                logging.exception('Failed to disable plugin during shutdown: %s', plugin_filename)

        self.active_plugins = []

        for plugin_filename in plugin_filenames:
            module_name = Path(plugin_filename).stem
            try:
                sys.modules.pop(module_name, None)
            except Exception:
                pass

    
    def run_pre_translation_plugins(self, text):
        """Run the shared pre-translation plugin pipeline and collect later phases."""
        if not PLUGINS_AVAILABLE:
            return text, text, [], []

        current_text = text
        clipboard_text = text
        translation_plugins = []
        post_translation_plugins = []
        translation_phase_started = False

        execution_order = [p for p in self.plugin_order if p in self.active_plugins]
        self.log_pipeline('pre_translation.start', incoming=text, active_plugins=execution_order)

        for plugin_filename in execution_order:
            if plugin_filename in self.plugins:
                plugin = self.plugins[plugin_filename]
                if not plugin.enabled:
                    continue

                if getattr(plugin, 'is_translation_plugin', False):
                    translation_phase_started = True
                    translation_plugins.append(plugin)
                    continue

                if translation_phase_started:
                    post_translation_plugins.append(plugin)
                    continue

                try:
                    if current_text is not None:
                        display_result = plugin.process_text(current_text)
                        if display_result is None:
                            self.log_pipeline('pre_translation.plugin_dropped', plugin=plugin_filename, incoming=current_text)
                        else:
                            self.log_pipeline('pre_translation.plugin_result', plugin=plugin_filename, output=display_result)
                        current_text = display_result

                    if clipboard_text is not None:
                        clipboard_result = plugin.process_clipboard_text(clipboard_text)
                        if clipboard_result is None:
                            self.log_pipeline('pre_translation.clipboard_plugin_dropped', plugin=plugin_filename, incoming=clipboard_text)
                        else:
                            self.log_pipeline('pre_translation.clipboard_plugin_result', plugin=plugin_filename, output=clipboard_result)
                        clipboard_text = clipboard_result
                except Exception:
                    pass

        if current_text is None:
            return None, clipboard_text, translation_plugins, post_translation_plugins

        self.log_pipeline('pre_translation.complete', output=current_text, clipboard_output=clipboard_text, translation_plugins=[getattr(p, 'name', type(p).__name__) for p in translation_plugins], post_plugins=[getattr(p, 'name', type(p).__name__) for p in post_translation_plugins])
        return current_text, clipboard_text, translation_plugins, post_translation_plugins

    def is_translation_worthy_output(self, text):
        stripped = text.strip() if isinstance(text, str) else text
        if not stripped:
            return False
        if isinstance(stripped, str) and (
            stripped.startswith('[Console]') or
            stripped.startswith('[Hook ') or
            stripped.startswith('[Hook #')
        ):
            return False
        return True

    def prepare_plugin_output_bundle(self, text, allow_auto_copy=False):
        """Run every stateful pre-translation plugin in lossless arrival order."""
        with self.output_processing_lock:
            current_text, clipboard_pre_translation, translation_plugins, post_translation_plugins = self.run_pre_translation_plugins(text)
        if current_text is None:
            self.log_pipeline('bundle.dropped_pre_translation', incoming=text, clipboard_pre_translation=clipboard_pre_translation)
            return None

        internal_marker_stripped = False
        if isinstance(current_text, str):
            internal_match = re.match(r'^\[Hook #?\d+\|\d+\]\s*(.*)$', current_text.strip(), re.DOTALL)
            if internal_match:
                current_text = internal_match.group(1) + ('\n' if current_text.endswith('\n') else '')
                internal_marker_stripped = True
        if isinstance(clipboard_pre_translation, str):
            clipboard_match = re.match(r'^\[Hook #?\d+\|\d+\]\s*(.*)$', clipboard_pre_translation.strip(), re.DOTALL)
            if clipboard_match:
                clipboard_pre_translation = clipboard_match.group(1) + ('\n' if clipboard_pre_translation.endswith('\n') else '')

        translator_input = current_text.strip() if isinstance(current_text, str) else current_text
        clipboard_text = clipboard_pre_translation.strip() if isinstance(clipboard_pre_translation, str) else clipboard_pre_translation
        translation_candidates = []
        if not internal_marker_stripped and self.is_translation_worthy_output(translator_input):
            for plugin in translation_plugins:
                should_translate = getattr(plugin, 'should_translate_text', None)
                try:
                    if callable(should_translate) and not should_translate(translator_input):
                        continue
                except Exception:
                    logging.exception('Translation eligibility check failed: %s', getattr(plugin, 'name', type(plugin).__name__))
                translation_candidates.append(plugin)
        incoming_is_hook_preview = isinstance(text, str) and text.lstrip().startswith('[Hook')
        output_is_hook_preview = isinstance(current_text, str) and current_text.lstrip().startswith('[Hook')
        effective_auto_copy = allow_auto_copy or (
            incoming_is_hook_preview and
            not output_is_hook_preview and
            not internal_marker_stripped
        )
        prepared = {
            'incoming': text,
            'current_text': current_text,
            'translator_input': translator_input,
            'clipboard_text': clipboard_text,
            'translation_plugins': tuple(translation_candidates),
            'post_translation_plugins': tuple(post_translation_plugins),
            'allow_auto_copy': effective_auto_copy,
        }
        self.log_pipeline('bundle.prepared', incoming=text, translator_input=translator_input, clipboard_text=clipboard_text, allow_auto_copy=effective_auto_copy, translation_plugin_count=len(translation_candidates), post_plugin_count=len(post_translation_plugins))
        return prepared

    def prepared_output_requires_translation(self, prepared):
        return bool(prepared['translation_plugins'])

    def complete_plugin_output_bundle(self, prepared):
        """Translate only the newest prepared logical line and run later plugins."""
        current_text = prepared['current_text']
        translator_input = prepared['translator_input']
        clipboard_text = prepared['clipboard_text']
        translation_plugins = prepared['translation_plugins']
        post_translation_plugins = prepared['post_translation_plugins']
        display_text = current_text

        if translation_plugins:
            translation_results = []
            self.log_pipeline('translation.request', translator_input=translator_input, display_source=current_text, clipboard_source=clipboard_text, translation_plugins=[getattr(p, 'name', type(p).__name__) for p in translation_plugins])
            for plugin in translation_plugins:
                try:
                    translated = plugin.translate_text(translator_input)
                    if translated:
                        translation_results.append((plugin.name, translated.strip()))
                        self.log_pipeline('translation.result', plugin=plugin.name, translated=translated.strip())
                    else:
                        self.log_pipeline('translation.empty', plugin=plugin.name, translator_input=translator_input)
                except Exception:
                    logging.exception('Translation plugin failed: %s', getattr(plugin, 'name', type(plugin).__name__))

            if len(translation_results) == 1:
                display_text = f"{current_text.rstrip()}\n{translation_results[0][1]}\n\n"
            elif translation_results:
                formatted_translations = "\n".join(
                    f"[{plugin_name}] {translated_text}"
                    for plugin_name, translated_text in translation_results
                )
                display_text = f"{current_text.rstrip()}\n{formatted_translations}\n\n"
            self.log_pipeline('bundle.translation_phase_complete', display_text=display_text, clipboard_text=clipboard_text)

        for plugin in post_translation_plugins:
            try:
                result = plugin.process_text(display_text)
                if result is None:
                    self.log_pipeline('post_translation.plugin_dropped', plugin=getattr(plugin, 'name', type(plugin).__name__), incoming=display_text)
                    return None, None
                self.log_pipeline('post_translation.plugin_result', plugin=getattr(plugin, 'name', type(plugin).__name__), output=result)
                display_text = result
            except Exception:
                logging.exception('Post-translation plugin failed: %s', getattr(plugin, 'name', type(plugin).__name__))

        self.log_pipeline('output.summary', translator_input=translator_input, output_window_text=display_text, clipboard_text=clipboard_text)
        return display_text, clipboard_text

    def remember_translation_context(self, prepared):
        translator_input = prepared['translator_input']
        for plugin in prepared['translation_plugins']:
            try:
                remember_line = getattr(plugin, 'remember_original_line', None)
                if callable(remember_line) and translator_input:
                    remember_line(translator_input)
            except Exception:
                logging.exception('Failed to remember translation context for %s', getattr(plugin, 'name', type(plugin).__name__))

    def deliver_plugin_output_bundle(self, completed, prepared):
        self.remember_translation_context(prepared)
        processed_text, clipboard_text = completed
        self.run_on_ui_thread(
            self._append_output_ui,
            processed_text,
            clipboard_text,
            prepared['allow_auto_copy'],
        )

    def handle_output_pipeline_error(self, stage, exc):
        logging.error('Output pipeline %s failed: %s: %s', stage, type(exc).__name__, exc, exc_info=(type(exc), exc, exc.__traceback__))
        self.run_on_ui_thread(self.notify_user, f"Output pipeline error during {stage}.", 'error', 6000)

    def handle_stale_output_bundle(self, prepared, generation, invalidated):
        self.log_pipeline('append_output.stale_discarded', incoming=prepared.get('incoming'), translator_input=prepared.get('translator_input'), generation=generation, invalidated=invalidated)

    def handle_superseded_output_bundle(self, prepared, generation):
        self.log_pipeline('append_output.superseded_delivered', incoming=prepared.get('incoming'), translator_input=prepared.get('translator_input'), generation=generation)

    def process_plugin_output_bundle(self, text):
        """Synchronously process one line for compatibility with direct callers."""
        prepared = self.prepare_plugin_output_bundle(text)
        if prepared is None:
            return None, None
        completed = self.complete_plugin_output_bundle(prepared)
        self.remember_translation_context(prepared)
        return completed

    def process_text_through_plugins(self, text):
        """Process text through all active plugins for display output."""
        processed_text, _clipboard_text = self.process_plugin_output_bundle(text)
        return processed_text

    def process_clipboard_text_through_plugins(self, text):
        """Process text through active plugins for clipboard-safe output."""
        _processed_text, clipboard_text = self.process_plugin_output_bundle(text)
        return clipboard_text

    def submit_output_processing(self, text, allow_auto_copy=False, front=False):
        """Queue raw text losslessly for ordered stateful preprocessing."""
        self.output_pipeline.submit(text, allow_auto_copy, front=front)
        self.log_pipeline('append_output.queued', incoming=text, allow_auto_copy=allow_auto_copy, front=front)

    def schedule_pipeline_callback(self, wait_ms, callback):
        epoch = self.output_pipeline.get_invalidation_epoch()
        cancelled = threading.Event()

        def run_serialized_callback():
            with self.output_processing_lock:
                if cancelled.is_set() or not self.output_pipeline.is_epoch_current(epoch):
                    return
                callback()

        pipeline_handle = self.output_pipeline.schedule_callback(wait_ms, run_serialized_callback)
        return pipeline_handle, cancelled

    def cancel_pipeline_callback(self, handle):
        if not handle:
            return
        pipeline_handle, cancelled = handle
        cancelled.set()
        self.output_pipeline.cancel_callback(pipeline_handle)

    def invalidate_output_processing(self, clear_pending=False):
        """Invalidate in-flight translation and optionally clear queued preprocessing."""
        self.output_pipeline.invalidate(clear_pending=clear_pending)

    def _append_output_ui(self, processed_text_value, clipboard_text_value, allow_auto_copy):
        self.log_pipeline('append_output.ui', processed_text=processed_text_value, clipboard_text=clipboard_text_value, allow_auto_copy=allow_auto_copy)
        if processed_text_value is not None:
            self.output_text.config(state='normal')
            self.output_text.insert(tk.END, processed_text_value)
            self.output_text.see(tk.END)
            self.output_text.config(state='disabled')
            self.update_statistics(processed_text_value)

        if self.auto_copy_enabled.get() and allow_auto_copy and clipboard_text_value is not None:
            self.log_pipeline('append_output.auto_copy', clipboard_text=clipboard_text_value, allow_auto_copy=allow_auto_copy)
            self.auto_copy_text(clipboard_text_value)
        else:
            self.log_pipeline('append_output.no_auto_copy', clipboard_text=clipboard_text_value, allow_auto_copy=allow_auto_copy, auto_copy_enabled=self.auto_copy_enabled.get())

    def reset_all_plugins(self):
        """Reset state of all plugins"""
        with self.output_processing_lock:
            self.invalidate_output_processing(clear_pending=True)
            for plugin in self.plugins.values():
                try:
                    plugin.reset()
                except Exception:
                    pass
    
    def open_plugins_folder(self):
        """Open the plugins folder in file explorer"""
        # Ensure the folder exists before opening
        if not self.plugins_folder.exists():
            self.plugins_folder.mkdir(parents=True, exist_ok=True)
        
        # Open the folder
        try:
            os.startfile(str(self.plugins_folder))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open plugins folder:\n{str(e)}")
    
    def refresh_plugins_list(self):
        """Refresh the plugins list in the UI"""
        if hasattr(self, 'plugins_tree'):
            self.plugins_tree.delete(*self.plugins_tree.get_children())
            
            # Ensure all loaded plugins are in plugin_order
            for filename in self.plugins:
                if filename not in self.plugin_order:
                    self.plugin_order.append(filename)
            
            # Display plugins in the order defined by plugin_order
            for index, filename in enumerate(self.plugin_order, start=1):
                if filename in self.plugins:
                    plugin = self.plugins[filename]
                    status = f"{index}. ✓ Active" if filename in self.active_plugins else f"{index}. ○ Inactive"
                    
                    # Check if plugin has settings to show configure button
                    has_settings = bool(plugin.get_settings())
                    actions = "⚙️ Configure" if has_settings else ""
                    
                    # We store the filename in the text attribute (hidden ID) for tracking
                    self.plugins_tree.insert('', tk.END, text=filename, values=(
                        status,
                        plugin.name,
                        plugin.version,
                        plugin.description[:50] + "..." if len(plugin.description) > 50 else plugin.description,
                        actions
                    ), tags=('active' if filename in self.active_plugins else 'inactive',))
        
        # Update count label
        if hasattr(self, 'plugins_count_label'):
            self.plugins_count_label.config(text=f"Active: {len(self.active_plugins)} plugins")

        self.update_plugin_action_buttons()

    def update_plugin_action_buttons(self):
        """Enable or disable plugin action buttons based on selection."""
        if not hasattr(self, 'plugin_toggle_btn'):
            return

        plugin_filename = self.get_selected_plugin_filename()
        state = 'normal' if plugin_filename else 'disabled'

        self.plugin_toggle_btn.config(state=state)
        self.plugin_move_up_btn.config(state=state)
        self.plugin_move_down_btn.config(state=state)

        if plugin_filename and plugin_filename in self.plugins and self.plugins[plugin_filename].get_settings():
            self.plugin_configure_btn.config(state='normal')
        else:
            self.plugin_configure_btn.config(state='disabled')

    def move_selected_plugin(self, direction):
        """Move the selected plugin up or down in execution order."""
        plugin_filename = self.get_selected_plugin_filename()
        if not plugin_filename:
            self.notify_user("Select a plugin to reorder.", level='warning')
            return

        try:
            current_index = self.plugin_order.index(plugin_filename)
        except ValueError:
            return

        new_index = current_index + direction
        if new_index < 0 or new_index >= len(self.plugin_order):
            return

        self.plugin_order[current_index], self.plugin_order[new_index] = self.plugin_order[new_index], self.plugin_order[current_index]
        self.save_plugins_config()
        self.refresh_plugins_list()

        for item in self.plugins_tree.get_children():
            if self.plugins_tree.item(item, 'text') == plugin_filename:
                self.plugins_tree.selection_set(item)
                self.plugins_tree.see(item)
                break

        self.notify_user("Plugin order updated.", level='success')

    def toggle_selected_plugin(self):
        """Toggle the selected plugin's active state"""
        if not hasattr(self, 'plugins_tree'):
            return

        plugin_filename = self.get_selected_plugin_filename()
        if not plugin_filename:
            self.notify_user("Select a plugin to toggle.", level='warning')
            return

        if plugin_filename in self.active_plugins:
            self.deactivate_plugin(plugin_filename)
            notice = f"Disabled {self.plugins[plugin_filename].name}."
        else:
            self.activate_plugin(plugin_filename)
            notice = f"Enabled {self.plugins[plugin_filename].name}."

        self.refresh_plugins_list()
        self.notify_user(notice, level='success')
    
    def add_plugin_from_file(self):
        """Add a new plugin by copying it to the plugins folder"""
        file_path = filedialog.askopenfilename(
            title="Select Plugin File",
            filetypes=[("Python files", "*.py"), ("All files", "*.*")],
            initialdir=str(Path.home())
        )
        
        if file_path:
            source_path = Path(file_path)
            dest_path = self.plugins_folder / source_path.name
            
            try:
                # Copy the file to plugins folder
                import shutil
                shutil.copy2(source_path, dest_path)
                
                # Load the new plugin
                plugin = self.load_plugin(dest_path)
                
                if plugin:
                    # Automatically activate the new plugin
                    self.activate_plugin(dest_path.name)
                    self.refresh_plugins_list()
                    self.notify_user(f"Plugin '{plugin.name}' added and activated.", level='success')
                else:
                    # Remove the file if it's not a valid plugin
                    dest_path.unlink()
                    messagebox.showerror("Error", "The selected file is not a valid SugoiHook plugin.")
                    
            except Exception as e:
                messagebox.showerror("Error", f"Failed to add plugin:\n{str(e)}")
    
    def remove_selected_plugin(self):
        """Remove the selected plugin"""
        if not hasattr(self, 'plugins_tree'):
            return
        
        selection = self.plugins_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a plugin to remove.")
            return
        
        item = self.plugins_tree.item(selection[0])
        plugin_name = item['values'][1]
        
        # Find the plugin filename by name
        plugin_filename = None
        for filename, plugin in self.plugins.items():
            if plugin.name == plugin_name:
                plugin_filename = filename
                break
        
        if plugin_filename:
            result = messagebox.askyesno(
                "Confirm Removal",
                f"Are you sure you want to remove the plugin '{plugin_name}'?\n\n"
                "This will delete the plugin file from the plugins folder."
            )
            
            if result:
                try:
                    plugin_path = self.plugin_file_paths.get(plugin_filename, self.plugins_folder / plugin_filename)
                    try:
                        is_user_plugin = plugin_path.resolve().parent == self.plugins_folder.resolve()
                    except Exception:
                        is_user_plugin = False
                    if not is_user_plugin:
                        messagebox.showwarning(
                            "Cannot Remove Built-in Plugin",
                            "This plugin is bundled with the application and cannot be deleted from the UI."
                        )
                        return

                    # Deactivate first
                    self.deactivate_plugin(plugin_filename)
                    
                    # Remove from plugins dict
                    del self.plugins[plugin_filename]
                    self.plugin_file_paths.pop(plugin_filename, None)
                    
                    # Remove from plugin_order
                    if plugin_filename in self.plugin_order:
                        self.plugin_order.remove(plugin_filename)
                    
                    # Delete the file
                    if plugin_path.exists():
                        plugin_path.unlink()
                    
                    # Save the updated configuration
                    self.save_plugins_config()
                    
                    self.refresh_plugins_list()
                    self.notify_user(f"Plugin '{plugin_name}' removed.", level='success')
                    
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to remove plugin:\n{str(e)}")
    
    def show_plugin_context_menu(self, event):
        """Show context menu for plugin with configure option"""
        # Select the item under cursor
        item = self.plugins_tree.identify_row(event.y)
        if item:
            self.plugins_tree.selection_set(item)
            
            # Get plugin info
            item_data = self.plugins_tree.item(item)
            plugin_name = item_data['values'][1]
            
            # Find the plugin filename
            plugin_filename = None
            for filename, plugin in self.plugins.items():
                if plugin.name == plugin_name:
                    plugin_filename = filename
                    break
            
            if not plugin_filename:
                return
            
            # Check if plugin has settings
            plugin = self.plugins[plugin_filename]
            has_settings = bool(plugin.get_settings())
            
            # Create context menu
            menu = tk.Menu(self.root, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
            
            # Toggle active/inactive
            if plugin_filename in self.active_plugins:
                menu.add_command(label="✓ Deactivate", command=self.toggle_selected_plugin)
            else:
                menu.add_command(label="○ Activate", command=self.toggle_selected_plugin)
            
            # Configure option (only if plugin has settings)
            if has_settings:
                menu.add_separator()
                menu.add_command(label="⚙️ Configure", command=self.configure_selected_plugin)
            
            # Show menu at cursor position
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
    
    def configure_selected_plugin(self):
        """Open configuration dialog for selected plugin with scrollable content"""
        selection = self.plugins_tree.selection()
        if not selection:
            return

        item = self.plugins_tree.item(selection[0])
        plugin_name = item['values'][1]

        plugin_filename = None
        for filename, plugin in self.plugins.items():
            if plugin.name == plugin_name:
                plugin_filename = filename
                break

        if not plugin_filename:
            return

        plugin = self.plugins[plugin_filename]
        dynamic_settings_fn = getattr(plugin, 'get_settings_for_values', None)
        draft_values = {}

        def get_dialog_settings():
            if callable(dynamic_settings_fn):
                return dynamic_settings_fn(draft_values)
            return plugin.get_settings()

        settings = get_dialog_settings()

        if not settings:
            self.notify_user(f"Plugin '{plugin_name}' has no configurable settings.", level='info')
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Configure {plugin_name}")
        dialog.geometry("800x900")
        dialog.configure(bg=self.colors['bg'])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.rowconfigure(0, weight=1)
        dialog.columnconfigure(0, weight=1)

        container = ttk.Frame(dialog, style="TFrame")
        container.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)
        container.rowconfigure(1, weight=1)
        container.columnconfigure(0, weight=1)

        title_card = ttk.Frame(container, style="Card.TFrame", padding=15)
        title_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(
            title_card,
            text=f"⚙️ {plugin_name} Settings",
            font=('Segoe UI', 14, 'bold'),
            foreground=self.colors['primary']
        ).pack()

        settings_card = ttk.Frame(container, style="Card.TFrame", padding=15)
        settings_card.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        settings_card.rowconfigure(0, weight=1)
        settings_card.columnconfigure(0, weight=1)

        canvas = tk.Canvas(settings_card, bg=self.colors['surface'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(settings_card, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas, style="Card.TFrame")

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=canvas.winfo_width())
        canvas.configure(yscrollcommand=scrollbar.set)

        def configure_canvas_width(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind('<Configure>', configure_canvas_width)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        def widget_is_descendant(child, ancestor):
            current = child
            while current is not None:
                if current == ancestor:
                    return True
                try:
                    parent_name = current.winfo_parent()
                except Exception:
                    return False
                if not parent_name:
                    return False
                try:
                    current = current._nametowidget(parent_name)
                except Exception:
                    return False
            return False

        def on_mousewheel(event):
            try:
                hovered = dialog.winfo_containing(event.x_root, event.y_root)
            except Exception:
                hovered = event.widget

            if hovered is None or not widget_is_descendant(hovered, canvas):
                return

            try:
                hovered_class = hovered.winfo_class().lower()
            except Exception:
                hovered_class = ''

            if hovered_class in {'tcombobox', 'combobox', 'listbox', 'text', 'entry', 'spinbox'}:
                return

            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"
        canvas.bind_all("<MouseWheel>", on_mousewheel)

        setting_widgets = {}
        overlay_preview = {'card': None, 'frame': None, 'translation': None, 'original': None, 'warning': None}

        def resolve_setting_value(var, options, value_type):
            if value_type in ('choice', 'color') and options:
                display_value = var.get()
                if value_type == 'color' and ' - ' in display_value:
                    return display_value.split(' - ')[0]
                for key, display in options.items():
                    if display == display_value or key == display_value:
                        return key
                return display_value
            if value_type == 'multiline_str':
                return var.get('1.0', tk.END).rstrip('\n')
            return var.get()

        def safe_preview_font(font_name, size, bold=False, italic=False):
            styles = []
            if bold:
                styles.append('bold')
            if italic:
                styles.append('italic')
            return (font_name, size, ' '.join(styles)) if styles else (font_name, size)

        def refresh_overlay_preview(*_args):
            if plugin_filename != 'overlay_window.py' or not overlay_preview['frame']:
                return
            try:
                values = {
                    name: resolve_setting_value(var, options, value_type)
                    for name, (var, options, value_type) in setting_widgets.items()
                }
                bg_color = values.get('bg_color', '#1e1e2e')
                border_color = values.get('border_color', self.colors['border'])
                overlay_preview['frame'].configure(
                    bg=bg_color,
                    highlightbackground=border_color,
                    highlightcolor=border_color
                )
                overlay_preview['translation'].configure(
                    bg=bg_color,
                    fg=values.get('translation_color', '#89b4fa'),
                    font=safe_preview_font(
                        values.get('translation_font', 'Segoe UI'),
                        int(values.get('translation_font_size', 14)),
                        bold=bool(values.get('translation_bold', True))
                    )
                )
                overlay_preview['original'].configure(
                    bg=bg_color,
                    fg=values.get('original_color', '#a6adc8'),
                    font=safe_preview_font(
                        values.get('original_font', 'Segoe UI'),
                        int(values.get('original_font_size', 10))
                    )
                )
                overlay_preview['warning'].configure(
                    bg=bg_color,
                    fg=values.get('warning_color', '#f9e2af'),
                    font=safe_preview_font(
                        values.get('warning_font', 'Segoe UI'),
                        int(values.get('warning_font_size', 12)),
                        italic=bool(values.get('warning_italic', True))
                    )
                )
            except Exception:
                pass

        def collect_current_draft_values():
            for setting_name, (var, options, value_type) in setting_widgets.items():
                draft_values[setting_name] = resolve_setting_value(var, options, value_type)

        def render_settings_form():
            nonlocal setting_widgets
            collect_current_draft_values()
            setting_widgets = {}

            for child in scrollable_frame.winfo_children():
                child.destroy()

            current_settings = get_dialog_settings()

            for setting_name, setting_info in current_settings.items():
                current_value, value_type, description, *options = setting_info
                options = options[0] if options else None

                if setting_name in draft_values:
                    current_value = draft_values[setting_name]

                setting_frame = ttk.Frame(scrollable_frame)
                setting_frame.pack(fill=tk.X, pady=8, padx=5)

                ttk.Label(
                    setting_frame,
                    text=description + ":",
                    font=('Segoe UI', 10, 'bold'),
                    foreground=self.colors['fg']
                ).pack(anchor=tk.W, pady=(0, 5))

                if value_type == 'color' and options:
                    color_frame = ttk.Frame(setting_frame)
                    color_frame.pack(fill=tk.X)
                    var = tk.StringVar(value=current_value)
                    combo = ttk.Combobox(color_frame, textvariable=var, width=35)
                    combo['values'] = [f"{key} - {value}" for key, value in options.items()]
                    if current_value in options:
                        combo.set(f"{current_value} - {options[current_value]}")
                    combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

                    preview_canvas = tk.Canvas(
                        color_frame,
                        width=40,
                        height=25,
                        bg=current_value,
                        highlightthickness=1,
                        highlightbackground=self.colors['border']
                    )
                    preview_canvas.pack(side=tk.LEFT)

                    def update_preview(event=None, combo=combo, preview_canvas=preview_canvas):
                        selected = combo.get()
                        if ' - ' in selected:
                            color_code = selected.split(' - ')[0]
                            try:
                                preview_canvas.config(bg=color_code)
                            except Exception:
                                pass
                        refresh_overlay_preview()

                    combo.bind('<<ComboboxSelected>>', update_preview)
                    combo.bind('<KeyRelease>', update_preview)
                    setting_widgets[setting_name] = (var, options, value_type)

                elif value_type == 'int_slider' and options:
                    slider_frame = ttk.Frame(setting_frame)
                    slider_frame.pack(fill=tk.X)
                    var = tk.IntVar(value=current_value)
                    value_label = ttk.Label(
                        slider_frame,
                        text=str(current_value),
                        font=('Segoe UI', 10, 'bold'),
                        foreground=self.colors['primary']
                    )
                    value_label.pack(side=tk.RIGHT, padx=(10, 0))
                    slider = tk.Scale(
                        slider_frame,
                        from_=options['min'],
                        to=options['max'],
                        orient=tk.HORIZONTAL,
                        variable=var,
                        bg=self.colors['surface'],
                        fg=self.colors['fg'],
                        highlightthickness=0,
                        troughcolor=self.colors['surface_light'],
                        activebackground=self.colors['primary'],
                        command=lambda v, label=value_label: label.config(text=str(int(float(v))))
                    )
                    slider.pack(side=tk.LEFT, fill=tk.X, expand=True)
                    var.trace_add('write', refresh_overlay_preview)
                    setting_widgets[setting_name] = (var, options, value_type)

                elif value_type == 'choice' and options:
                    var = tk.StringVar(value=current_value)
                    combo = ttk.Combobox(setting_frame, textvariable=var)
                    combo['values'] = [options.get(key, key) for key in options.keys()]
                    if current_value in options:
                        combo.set(options[current_value])
                    combo.pack(fill=tk.X)

                    def on_choice_change(event=None, setting_name=setting_name, var=var, options=options, value_type=value_type):
                        draft_values[setting_name] = resolve_setting_value(var, options, value_type)
                        refresh_overlay_preview()
                        if setting_name == 'provider' and callable(dynamic_settings_fn):
                            render_settings_form()

                    combo.bind('<<ComboboxSelected>>', on_choice_change)
                    combo.bind('<KeyRelease>', refresh_overlay_preview)
                    setting_widgets[setting_name] = (var, options, value_type)

                elif value_type == 'bool':
                    var = tk.BooleanVar(value=current_value)
                    check = ttk.Checkbutton(setting_frame, text="Enabled", variable=var)
                    check.pack(anchor=tk.W)
                    var.trace_add('write', refresh_overlay_preview)
                    setting_widgets[setting_name] = (var, None, value_type)

                elif value_type == 'int':
                    var = tk.IntVar(value=current_value)
                    entry = ttk.Entry(setting_frame, textvariable=var)
                    entry.pack(fill=tk.X)
                    var.trace_add('write', refresh_overlay_preview)
                    setting_widgets[setting_name] = (var, None, value_type)

                elif value_type == 'secret':
                    var = tk.StringVar(value=current_value)
                    entry = ttk.Entry(setting_frame, textvariable=var, show='*')
                    entry.pack(fill=tk.X)
                    setting_widgets[setting_name] = (var, None, value_type)

                elif value_type == 'multiline_str':
                    text_frame = ttk.Frame(setting_frame)
                    text_frame.pack(fill=tk.BOTH, expand=True)
                    text_frame.columnconfigure(0, weight=1)
                    text_frame.rowconfigure(0, weight=1)
                    text_widget = tk.Text(
                        text_frame,
                        height=10,
                        wrap=tk.WORD,
                        bg=self.colors['surface'],
                        fg=self.colors['fg'],
                        insertbackground=self.colors['fg'],
                        relief=tk.FLAT,
                        borderwidth=1
                    )
                    text_scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
                    text_widget.configure(yscrollcommand=text_scrollbar.set)
                    text_widget.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
                    text_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
                    if current_value:
                        text_widget.insert('1.0', current_value)
                    setting_widgets[setting_name] = (text_widget, None, value_type)

                else:
                    var = tk.StringVar(value=current_value)
                    entry = ttk.Entry(setting_frame, textvariable=var)
                    entry.pack(fill=tk.X)
                    setting_widgets[setting_name] = (var, None, value_type)

            refresh_overlay_preview()

        render_settings_form()

        if plugin_filename == 'overlay_window.py':
            preview_card = ttk.Frame(container, style="Card.TFrame", padding=15)
            preview_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
            ttk.Label(
                preview_card,
                text="Live Preview",
                font=('Segoe UI', 11, 'bold'),
                foreground=self.colors['primary']
            ).pack(anchor=tk.W, pady=(0, 8))
            preview_frame = tk.Frame(
                preview_card,
                bg='#1e1e2e',
                highlightthickness=1,
                highlightbackground=self.colors['border'],
                padx=14,
                pady=12
            )
            preview_frame.pack(fill=tk.X)
            translation_label = tk.Label(preview_frame, text='Girl: "Do I look a little tired?"', anchor='w', justify='left')
            translation_label.pack(fill=tk.X)
            original_label = tk.Label(preview_frame, text='少女「少し疲れた感じ、出てるかな」', anchor='w', justify='left', pady=4)
            original_label.pack(fill=tk.X)
            warning_label = tk.Label(preview_frame, text='Please enable the translation plugin', anchor='w', justify='left')
            warning_label.pack(fill=tk.X, pady=(6, 0))
            overlay_preview.update({
                'card': preview_card,
                'frame': preview_frame,
                'translation': translation_label,
                'original': original_label,
                'warning': warning_label,
            })
            refresh_overlay_preview()

        btn_card = ttk.Frame(container, style="Card.TFrame", padding=15)
        btn_card.grid(row=3, column=0, sticky="ew")

        def save_settings():
            if plugin_filename not in self.plugin_settings:
                self.plugin_settings[plugin_filename] = {}

            collect_current_draft_values()

            with self.output_processing_lock:
                for setting_name, value in draft_values.items():
                    plugin.set_setting(setting_name, value)
                    self.plugin_settings[plugin_filename][setting_name] = value

            self.save_plugins_config()
            self.update_hook_status_panel()
            self.update_hook_action_state()
            canvas.unbind_all("<MouseWheel>")
            self.notify_user(f"Saved settings for {plugin_name}.", level='success')
            dialog.destroy()

        def cancel():
            canvas.unbind_all("<MouseWheel>")
            dialog.destroy()

        btn_container = ttk.Frame(btn_card)
        btn_container.pack(expand=True)
        ttk.Button(btn_container, text="💾 Save Settings", command=save_settings, style="TButton").pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_container, text="✖️ Cancel", command=cancel, style="Disclosure.TButton").pack(side=tk.LEFT)

        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.protocol("WM_DELETE_WINDOW", cancel)

    # ==================== END PLUGIN SYSTEM METHODS =============    
    # ==================== GAME PROFILES SYSTEM METHODS =============    
    def generate_game_id(self, pid):
        """Generate unique identifier for a game based on exe path and size"""
        try:
            proc = psutil.Process(pid)
            exe_path = proc.exe()
            exe_size = Path(exe_path).stat().st_size
            
            # Generate unique ID from path and size
            unique_string = f"{exe_path}_{exe_size}"
            game_id = hashlib.md5(unique_string.encode()).hexdigest()
            
            return game_id, exe_path, exe_size
        except Exception:
            return None, None, None
    
    def load_game_profiles(self):
        """Load game profiles from JSON file"""
        self.game_profiles = {}
        if self.game_profiles_path and self.game_profiles_path.exists():
            try:
                with open(self.game_profiles_path, 'r', encoding='utf-8') as f:
                    self.game_profiles = json.load(f)
            except Exception:
                pass
    
    def save_game_profiles(self):
        """Save game profiles to JSON file"""
        if self.game_profiles_path:
            try:
                # Ensure directory exists
                if not self.game_profiles_path.parent.exists():
                    self.game_profiles_path.parent.mkdir(parents=True, exist_ok=True)
                    
                with open(self.game_profiles_path, 'w', encoding='utf-8') as f:
                    json.dump(self.game_profiles, f, indent=2)
            except Exception:
                pass
    
    def save_hook_profile(self, hook_id=None, hook_code=None):
        """Save current hook selection to game profile"""
        if not self.current_game_id or not self.attached_pid:
            return
        
        try:
            # Get process info
            proc = psutil.Process(self.attached_pid)
            exe_name = proc.name()
            exe_path = proc.exe()
            exe_size = Path(exe_path).stat().st_size
            arch = self.get_process_architecture(self.attached_pid)
            
            # Determine hook type and data
            text_sample = ""
            if hook_code:
                hook_type = "manual"
                hook_data = hook_code
                hook_function = "Manual Hook"
            elif hook_id and hook_id in self.hooks:
                hook_type = "auto"
                hook_data = hook_id
                hook_function = self.hooks[hook_id].get('function', 'Unknown')
                # Save text sample to help identify the correct hook later
                texts = self.hooks[hook_id].get('texts', [])
                if texts:
                    # Get first non-empty text as sample
                    for text in texts:
                        if text and text.strip():
                            text_sample = text.strip()[:100]  # First 100 chars
                            break
            else:
                return
            
            # Create or update profile
            self.game_profiles[self.current_game_id] = {
                'exe_name': exe_name,
                'exe_path': exe_path,
                'exe_size': exe_size,
                'hook_type': hook_type,
                'hook_data': hook_data,
                'hook_function': hook_function,
                'text_sample': text_sample,  # Save text sample for better matching
                'last_used': time.strftime('%Y-%m-%d %H:%M:%S'),
                'architecture': arch,
                'engine': self.current_engine  # Remember which engine was used
            }
            
            # Save to file
            self.save_game_profiles()
            
            # Show brief notification
            self.append_event(f"💾 Hook profile saved for {exe_name}\n")
            
        except Exception:
            pass
    
    def check_and_load_hook_profile(self):
        """Check if game profile exists and prepare auto-hook"""
        if not self.attached_pid:
            return
        
        # Load profiles if not already loaded
        if not self.game_profiles:
            self.load_game_profiles()
        
        # Generate game ID
        game_id, exe_path, exe_size = self.generate_game_id(self.attached_pid)
        
        if not game_id:
            return
        
        self.current_game_id = game_id
        
        # Check if profile exists
        if game_id in self.game_profiles:
            profile = self.game_profiles[game_id]
            
            # Only show messages if not in silent launch mode
            if not self.silent_auto_launch:
                # Show notification
                self.append_event(f"🔍 Found saved profile for {profile['exe_name']}\n")
                self.append_event(f"⌛ Will auto-select hook: {profile['hook_function']}\n\n")
            
            # Set auto-hook pending flag
            self.auto_hook_pending = True
            self.auto_hook_data = profile
            self.update_hook_status_panel("found saved hook profile")
    
    def attempt_auto_hook(self):
        """Attempt to automatically select saved hook with improved matching"""
        if not self.auto_hook_pending or not self.auto_hook_data:
            return
        
        profile = self.auto_hook_data
        
        try:
            if profile['hook_type'] == 'manual':
                # Auto-attach manual hook
                hook_code = profile['hook_data']
                
                if self.cli_process and self.attached_pid:
                    command = f"{hook_code} -P{self.attached_pid}\n"
                    self.cli_process.stdin.write(command)
                    self.cli_process.stdin.flush()
                    
                    self.append_event(f"✓ Auto-attached manual hook: {hook_code}\n\n")
                    self.update_hook_status_panel(f"auto-attached manual hook {hook_code}")
                    self.notify_user("Saved manual hook applied.", level='success')
                    self.auto_hook_pending = False
                    self.auto_hook_data = None
                    
            elif profile['hook_type'] == 'auto':
                # Try to find the correct hook using multiple strategies
                saved_hook_id = str(profile['hook_data'])
                saved_function = profile.get('hook_function', '')
                saved_text_sample = profile.get('text_sample', '')
                
                matched_hook_id = None
                
                # Strategy 1: Try exact hook ID match first
                if saved_hook_id in self.hooks:
                    # Check if there are multiple hooks with same function name
                    hooks_with_same_function = [
                        hid for hid, hook in self.get_hooks_snapshot().items()
                        if hook.get('function') == saved_function
                    ]
                    
                    if len(hooks_with_same_function) == 1:
                        # Only one hook with this function, safe to use
                        matched_hook_id = saved_hook_id
                    elif len(hooks_with_same_function) > 1 and saved_text_sample:
                        # Multiple hooks with same function - use text sample matching
                        best_match_id = None
                        best_match_score = 0
                        
                        for hook_id in hooks_with_same_function:
                            hook_texts = self.hooks[hook_id].get('texts', [])
                            for hook_text in hook_texts:
                                if hook_text and hook_text.strip():
                                    # Calculate similarity (simple substring match)
                                    text_clean = hook_text.strip()[:100]
                                    if saved_text_sample in text_clean or text_clean in saved_text_sample:
                                        # Strong match - text samples overlap
                                        best_match_id = hook_id
                                        best_match_score = 100
                                        break
                            if best_match_score == 100:
                                break
                        
                        if best_match_id:
                            matched_hook_id = best_match_id
                            self.append_event(f"🎯 Matched hook by text sample (multiple hooks with same function)\n")
                        else:
                            # Fallback: use saved hook ID anyway
                            matched_hook_id = saved_hook_id
                            self.append_event(f"⚠️ Multiple hooks with same function - using saved ID\n")
                    else:
                        matched_hook_id = saved_hook_id
                
                # Strategy 2: If saved ID not found, try matching by function + text sample
                if not matched_hook_id and saved_function:
                    hooks_with_function = [
                        hid for hid, hook in self.get_hooks_snapshot().items()
                        if hook.get('function') == saved_function
                    ]
                    
                    if len(hooks_with_function) == 1:
                        matched_hook_id = hooks_with_function[0]
                        self.append_event(f"🔍 Matched hook by function name\n")
                    elif len(hooks_with_function) > 1 and saved_text_sample:
                        # Use text sample to find correct hook
                        for hook_id in hooks_with_function:
                            hook_texts = self.hooks[hook_id].get('texts', [])
                            for hook_text in hook_texts:
                                if hook_text and hook_text.strip():
                                    text_clean = hook_text.strip()[:100]
                                    if saved_text_sample in text_clean or text_clean in saved_text_sample:
                                        matched_hook_id = hook_id
                                        self.append_event(f"🎯 Matched hook by text sample\n")
                                        break
                            if matched_hook_id:
                                break
                
                # Select the matched hook
                if matched_hook_id and self.cli_process:
                    try:
                        self.cli_process.stdin.write(f"select {matched_hook_id}\n")
                        self.cli_process.stdin.flush()
                        
                        self.selected_hook_id = matched_hook_id
                        
                        # Only show messages if not in silent launch  mode
                        if not self.silent_auto_launch:
                            self.append_event(f"✓ Auto-selected Hook {matched_hook_id}\n")
                            self.append_event(f"Function: {saved_function}\n")
                            self.append_event("─" * 50 + "\n\n")
                        else:
                            # Silent mode - just show brief success message
                            self.append_event(f"✓ Game ready! Text extraction active.\n\n")
                        
                        self.auto_hook_pending = False
                        self.auto_hook_data = None
                        self.silent_auto_launch = False  # Reset silent mode flag
                        self.update_hook_status_panel(f"auto-selected hook {matched_hook_id}")
                        self.notify_user(f"Auto-selected hook {matched_hook_id}.", level='success')
                        if hasattr(self, '_auto_hook_scheduled'):
                            delattr(self, '_auto_hook_scheduled')
                        
                    except Exception:
                        pass
                else:
                    # Could not find matching hook - retry if attempts remain
                    if hasattr(self, '_auto_hook_retry_count') and self._auto_hook_retry_count < 3:
                        self._auto_hook_retry_count += 1
                        # Only show retry messages if not in silent mode
                        if not self.silent_auto_launch:
                            self.append_event(f"🔄 Hook not found yet, retrying in 5 seconds... (Attempt {self._auto_hook_retry_count + 1}/4)\n")
                        self.root.after(5000, self.attempt_auto_hook)
                    else:
                        # All retries exhausted
                        if not self.silent_auto_launch:
                            self.append_event(f"⚠️ Could not find matching hook after multiple attempts - please select manually\n\n")
                        else:
                            self.append_event(f"⚠️ Auto-hook failed - please select hook manually from the list above.\n\n")
                        self.auto_hook_pending = False
                        self.auto_hook_data = None
                        self.silent_auto_launch = False  # Reset silent mode flag
                        self.update_hook_status_panel("auto-hook failed")
                        self.notify_user("Saved hook was not found automatically.", level='warning')
                        if hasattr(self, '_auto_hook_scheduled'):
                            delattr(self, '_auto_hook_scheduled')
                    
        except Exception:
            pass
    
    def browse_and_attach_exe(self):
        """Browse for an executable file and attach to it"""
        # Open file dialog to select executable
        exe_path = filedialog.askopenfilename(
            title="Select Executable to Launch",
            filetypes=[("Executable files", "*.exe"), ("All files", "*.*")],
            initialdir=str(Path.home())
        )
        
        if not exe_path:
            return
        
        exe_path = Path(exe_path)
        
        if not exe_path.exists():
            messagebox.showerror("Error", f"File not found:\n{exe_path}")
            return
        
        try:
            # Launch the executable
            subprocess.Popen([str(exe_path)], shell=True)
            
            # Show notification in output
            self.append_event(f"🚀 Launching: {exe_path.name}\n")
            self.append_event("⏳ Waiting for process to start...\n\n")
            
            # Start a thread to monitor and auto-attach
            def monitor_and_attach():
                # Wait a bit for the process to start
                time.sleep(3)
                
                # Try to find the process (try for up to 30 seconds)
                max_attempts = 30
                for attempt in range(max_attempts):
                    try:
                        # Look for process by executable path
                        for proc in psutil.process_iter(['pid', 'exe']):
                            try:
                                proc_exe = proc.info.get('exe', '')
                                if proc_exe and os.path.normpath(proc_exe.lower()) == os.path.normpath(str(exe_path).lower()):
                                    # Found the process
                                    pid = proc.info['pid']
                                    
                                    # Update UI in main thread
                                    def attach_to_game():
                                        # Check if already attached
                                        if self.attached_pid:
                                            self.append_event("⚠️ Already attached to a process. Detaching first...\n")
                                            self.detach_process()
                                            time.sleep(0.5)
                                        
                                        # Refresh process list to include the new game
                                        self.refresh_processes()
                                        
                                        # Find and select the process in the tree
                                        for tree_item in self.process_tree.get_children():
                                            tree_values = self.process_tree.item(tree_item)['values']
                                            if tree_values[0] == pid:
                                                self.process_tree.selection_set(tree_item)
                                                self.process_tree.see(tree_item)
                                                break
                                        
                                        # Wait a bit to ensure the UI is updated and selection is properly set
                                        def perform_attach():
                                            self.attach_process()
                                            self.append_event(f"✓ Process launched and attached successfully!\n")
                                            self.append_event(f"⏳ Please interact with the application to capture text...\n\n")
                                        
                                        # Delay attachment by 2 seconds to ensure UI is ready
                                        self.root.after(2000, perform_attach)
                                    
                                    self.root.after(0, attach_to_game)
                                    return
                            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                                continue
                    except Exception:
                        pass
                    
                    # Wait before next attempt
                    time.sleep(1)
                
                # If we get here, process was not found
                self.root.after(0, lambda: self.append_event(
                    "⚠️ Could not find process after 30 seconds.\n"
                    "   Please attach manually if the application is running.\n\n"
                ))
            
            threading.Thread(target=monitor_and_attach, daemon=True).start()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to launch executable:\n{str(e)}")
    
    def open_profile_manager(self):
        """Open game profile management window"""
        # Load profiles
        self.load_game_profiles()
        
        # Create profile manager window
        manager = tk.Toplevel(self.root)
        manager.title("💾 Manage Game Profiles")
        manager.geometry("1500x550")
        manager.minsize(1500, 550)
        manager.configure(bg=self.colors['bg'])
        manager.transient(self.root)
        manager.grab_set()
        
        # Main container
        container = ttk.Frame(manager, style="TFrame")
        container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)
        
        # Title section
        title_frame = ttk.Frame(container, style="Card.TFrame", padding=15)
        title_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        title_frame.columnconfigure(0, weight=1)
        
        ttk.Label(title_frame, text="💾 Saved Game Profiles", 
                 font=('Segoe UI', 16, 'bold'),
                 foreground=self.colors['primary']).pack()
        
        ttk.Label(title_frame, text=f"Total profiles: {len(self.game_profiles)}",
                 font=('Segoe UI', 10),
                 foreground=self.colors['text_dim']).pack(pady=(5, 0))
        
        # Profile list card
        list_card = ttk.Frame(container, style="Card.TFrame", padding=15)
        list_card.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 15))
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(0, weight=1)
        
        # Create treeview with better column layout
        columns = ('game', 'engine', 'hook_type', 'hook_info', 'last_used')
        profiles_tree = ttk.Treeview(list_card, columns=columns, show='headings', height=12)
        
        # Configure headings
        profiles_tree.heading('game', text='Game')
        profiles_tree.heading('engine', text='Engine')
        profiles_tree.heading('hook_type', text='Type')
        profiles_tree.heading('hook_info', text='Hook Info')
        profiles_tree.heading('last_used', text='Last Used')
        
        # Configure columns with center alignment
        profiles_tree.column('game', width=180, anchor='center')
        profiles_tree.column('engine', width=80, anchor='center')
        profiles_tree.column('hook_type', width=80, anchor='center')
        profiles_tree.column('hook_info', width=280, anchor='center')
        profiles_tree.column('last_used', width=140, anchor='center')
        
        scrollbar = ttk.Scrollbar(list_card, orient=tk.VERTICAL, command=profiles_tree.yview)
        profiles_tree.configure(yscrollcommand=scrollbar.set)
        
        profiles_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # Populate profiles
        for game_id, profile in self.game_profiles.items():
            engine_name = "🌙 Luna"
            hook_type = "🔧 Manual" if profile['hook_type'] == 'manual' else "🎯 Auto"
            hook_info = profile.get('hook_data', 'Unknown')
            if profile['hook_type'] == 'auto':
                hook_function = profile.get('hook_function', 'Unknown')
                hook_info = f"ID {hook_info} - {hook_function}"
            
            profiles_tree.insert('', tk.END, text=game_id, values=(
                profile['exe_name'],
                engine_name,
                hook_type,
                hook_info,
                profile.get('last_used', 'Unknown')
            ))
        
        # Buttons frame - centered
        btn_card = ttk.Frame(container, style="Card.TFrame", padding=15)
        btn_card.grid(row=2, column=0, sticky=(tk.W, tk.E))
        
        # Center the buttons
        btn_container = ttk.Frame(btn_card)
        btn_container.pack(expand=True)
        
        def delete_selected():
            """Delete selected profile"""
            selection = profiles_tree.selection()
            if not selection:
                messagebox.showwarning("No Selection", "Please select a profile to delete.")
                return
            
            item = profiles_tree.item(selection[0])
            game_id = profiles_tree.item(selection[0], 'text')
            game_name = item['values'][0]
            
            result = messagebox.askyesno(
                "Confirm Deletion",
                f"Delete profile for '{game_name}'?"
            )
            
            if result:
                del self.game_profiles[game_id]
                self.save_game_profiles()
                profiles_tree.delete(selection[0])
                # Update title count
                for widget in title_frame.winfo_children():
                    if isinstance(widget, ttk.Label) and 'Total profiles' in str(widget.cget('text')):
                        widget.config(text=f"Total profiles: {len(self.game_profiles)}")
                self.notify_user("Profile deleted.", level='success')
        
        def launch_game():
            """Launch the selected game and auto-attach"""
            selection = profiles_tree.selection()
            if not selection:
                messagebox.showwarning("No Selection", "Please select a profile to launch.")
                return
            
            item = profiles_tree.item(selection[0])
            game_id = profiles_tree.item(selection[0], 'text')
            game_name = item['values'][0]
            
            if game_id not in self.game_profiles:
                return
            
            profile = self.game_profiles[game_id]
            exe_path = profile.get('exe_path', '')
            if not exe_path or not os.path.exists(exe_path):
                messagebox.showerror("Error", 
                    f"Game executable not found:\n{exe_path}\n\n"
                    "The game may have been moved or uninstalled.")
                return
            
            try:
                # Set silent auto-launch flag to suppress hook messages
                self.silent_auto_launch = True
                
                # Close the profile manager window
                manager.destroy()
                
                # Launch the game
                subprocess.Popen([exe_path], shell=True)
                
                # Show notification in output
                self.append_event(f"🚀 Launching game: {game_name}\n")
                self.append_event("⏳ Waiting for process to start and auto-hook...\n\n")
                self.append_event("⏳ Wait around 3-5 seconds after the game is launched then you should see further updates...\n\n")
                
                # Start a thread to monitor and auto-attach
                def monitor_and_attach():
                    # Wait a bit for the game to start
                    time.sleep(3)
                    
                    # Try to find the process (try for up to 30 seconds)
                    max_attempts = 30
                    for attempt in range(max_attempts):
                        try:
                            # Look for process by executable path
                            for proc in psutil.process_iter(['pid', 'exe']):
                                try:
                                    proc_exe = proc.info.get('exe', '')
                                    if proc_exe and os.path.normpath(proc_exe.lower()) == os.path.normpath(exe_path.lower()):
                                        # Found the process
                                        pid = proc.info['pid']
                                        
                                        # Update UI in main thread
                                        def attach_to_game():
                                            # Check if already attached
                                            if self.attached_pid:
                                                self.append_event("⚠️ Already attached to a process. Detaching first...\n")
                                                self.detach_process()
                                                time.sleep(0.5)
                                            
                                            # Refresh process list to include the new game
                                            self.refresh_processes()
                                            
                                            # Find and select the process in the tree
                                            for tree_item in self.process_tree.get_children():
                                                tree_values = self.process_tree.item(tree_item)['values']
                                                if tree_values[0] == pid:
                                                    self.process_tree.selection_set(tree_item)
                                                    self.process_tree.see(tree_item)
                                                    break
                                            
                                            # Wait a bit to ensure the UI is updated and selection is properly set
                                            # This prevents "No Selection" errors
                                            def perform_attach():
                                                self.attach_process()
                                                self.append_event(f"✓ Game launched and attached successfully!\n")
                                                self.append_event(f"⏳ Please start the game and click on a dialogue or two and wait a bit...\n\n")
                                                self.append_event(f"⏳ Game hook will automatically be applied after that...\n\n")

                                            # Delay attachment by 4 second to ensure UI is ready
                                            self.root.after(4000, perform_attach)
                                        
                                        self.root.after(0, attach_to_game)
                                        return
                                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                                    continue
                        except Exception:
                            pass
                        
                        # Wait before next attempt
                        time.sleep(1)
                    
                    # If we get here, process was not found
                    self.root.after(0, lambda: self.append_event(
                        "⚠️ Could not find game process after 30 seconds.\n"
                        "   Please attach manually if the game is running.\n\n"
                    ))
                
                threading.Thread(target=monitor_and_attach, daemon=True).start()
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to launch game:\n{str(e)}")
        
        def clear_all():
            """Clear all profiles"""
            if not self.game_profiles:
                messagebox.showinfo("Info", "No profiles to clear.")
                return
            
            result = messagebox.askyesno(
                "Confirm Clear All",
                f"Delete all {len(self.game_profiles)} profiles?\n\nThis cannot be undone."
            )
            
            if result:
                self.game_profiles = {}
                self.save_game_profiles()
                profiles_tree.delete(*profiles_tree.get_children())
                # Update title count
                for widget in title_frame.winfo_children():
                    if isinstance(widget, ttk.Label) and 'Total profiles' in str(widget.cget('text')):
                        widget.config(text=f"Total profiles: 0")
                self.notify_user("All profiles cleared.", level='success')
        
        ttk.Button(btn_container, text="🚀 Launch Game", 
                  command=launch_game,
                  style="TButton").pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_container, text="🗑️ Delete Selected", 
                  command=delete_selected,
                  style="Secondary.TButton").pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_container, text="🗑️ Clear All", 
                  command=clear_all,
                  style="Danger.TButton").pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_container, text="✖️ Close", 
                  command=manager.destroy,
                  style="Secondary.TButton").pack(side=tk.LEFT, padx=5)
        
        # Center the window
        manager.update_idletasks()
        x = (manager.winfo_screenwidth() // 2) - (manager.winfo_width() // 2)
        y = (manager.winfo_screenheight() // 2) - (manager.winfo_height() // 2)
        manager.geometry(f"+{x}+{y}")
    
    # ==================== END GAME PROFILES SYSTEM METHODS =============    
    def setup_modern_theme(self):
        """Create a modern custom theme"""
        style = ttk.Style()
        
        # Configure root window
        self.root.configure(bg=self.colors['bg'])
        
        # Create custom style
        style.theme_create("modern", parent="alt", settings={
            ".": {
                "configure": {
                    "background": self.colors['bg'],
                    "foreground": self.colors['fg'],
                    "bordercolor": self.colors['border'],
                    "darkcolor": self.colors['surface'],
                    "lightcolor": self.colors['surface_light'],
                    "troughcolor": self.colors['surface'],
                    "focuscolor": self.colors['primary'],
                    "selectbackground": self.colors['primary'],
                    "selectforeground": self.colors['bg'],
                    "fieldbackground": self.colors['surface'],
                    "font": ('Segoe UI', 10),
                    "borderwidth": 0
                }
            },
            "TFrame": {
                "configure": {
                    "background": self.colors['bg']
                }
            },
            "Card.TFrame": {
                "configure": {
                    "background": self.colors['surface'],
                    "relief": "flat",
                    "borderwidth": 1
                }
            },
            "TLabel": {
                "configure": {
                    "background": self.colors['bg'],
                    "foreground": self.colors['fg'],
                    "font": ('Segoe UI', 10)
                }
            },
            "Title.TLabel": {
                "configure": {
                    "font": ('Segoe UI', 12, 'bold'),
                    "foreground": self.colors['primary']
                }
            },
            "Status.TLabel": {
                "configure": {
                    "font": ('Segoe UI', 9),
                    "padding": (10, 5)
                }
            },
            "TButton": {
                "configure": {
                    "background": self.colors['primary'],
                    "foreground": self.colors['bg'],
                    "borderwidth": 0,
                    "focuscolor": "none",
                    "padding": (20, 10),
                    "font": ('Segoe UI', 9, 'bold')
                },
                "map": {
                    "background": [("active", self.colors['accent']), ("disabled", self.colors['surface'])],
                    "foreground": [("disabled", self.colors['text_dim'])]
                }
            },
            "Secondary.TButton": {
                "configure": {
                    "background": self.colors['surface_light'],
                    "foreground": self.colors['fg'],
                    "padding": (15, 8)
                },
                "map": {
                    "background": [("active", self.colors['border'])]
                }
            },
            "Disclosure.TButton": {
                "configure": {
                    "background": self.colors['surface_light'],
                    "foreground": self.colors['fg'],
                    "padding": (5, 2),
                    "font": ('Segoe UI', 10, 'bold')
                },
                "map": {
                    "background": [("active", self.colors['border'])]
                }
            },
            "Danger.TButton": {
                "configure": {
                    "background": self.colors['secondary'],
                    "foreground": self.colors['bg'],
                    "padding": (15, 8)
                },
                "map": {
                    "background": [("active", "#f5c2e7")]
                }
            },
            "TEntry": {
                "configure": {
                    "fieldbackground": self.colors['surface'],
                    "foreground": self.colors['fg'],
                    "bordercolor": self.colors['border'],
                    "lightcolor": self.colors['surface'],
                    "darkcolor": self.colors['surface'],
                    "insertcolor": self.colors['primary'],
                    "padding": (10, 8),
                    "font": ('Segoe UI', 10)
                },
                "map": {
                    "fieldbackground": [("focus", self.colors['surface_light'])],
                    "bordercolor": [("focus", self.colors['primary'])]
                }
            },
            "Treeview": {
                "configure": {
                    "background": self.colors['surface'],
                    "foreground": self.colors['fg'],
                    "fieldbackground": self.colors['surface'],
                    "borderwidth": 0,
                    "font": ('Segoe UI', 9),
                    "rowheight": 32
                },
                "map": {
                    "background": [("selected", self.colors['primary'])],
                    "foreground": [("selected", self.colors['bg'])]
                }
            },
            "Treeview.Heading": {
                "configure": {
                    "background": self.colors['surface_light'],
                    "foreground": self.colors['accent'],
                    "borderwidth": 0,
                    "font": ('Segoe UI', 9, 'bold'),
                    "padding": (10, 8)
                },
                "map": {
                    "background": [("active", self.colors['border'])]
                }
            },
            "Vertical.TScrollbar": {
                "configure": {
                    "background": self.colors['surface'],
                    "troughcolor": self.colors['bg'],
                    "borderwidth": 0,
                    "arrowsize": 14
                },
                "map": {
                    "background": [("active", self.colors['border'])]
                }
            },
            "TCheckbutton": {
                "configure": {
                    "background": self.colors['bg'],
                    "foreground": self.colors['fg'],
                    "font": ('Segoe UI', 9),
                    "indicatorcolor": self.colors['surface_light'],
                    "indicatorrelief": "flat",
                    "borderwidth": 1,
                    "relief": "flat"
                },
                "map": {
                    "foreground": [("active", self.colors['fg']), ("disabled", self.colors['text_dim'])],
                    "background": [("active", self.colors['bg'])],
                    "indicatorcolor": [("selected", self.colors['primary']), ("active", self.colors['border'])]
                }
            }
        })
        
        style.theme_use("modern")
    
    def set_window_icon(self):
        """Set the window icon from logo.webp"""
        try:
            if self.logo_path.exists():
                # Load the webp image
                logo_img = Image.open(self.logo_path)
                # Convert to PhotoImage for tkinter
                logo_photo = ImageTk.PhotoImage(logo_img)
                # Set as window icon
                self.root.iconphoto(True, logo_photo)
                # Store reference to prevent garbage collection
                self.root._logo_photo = logo_photo
        except Exception:
            pass
        
    def setup_ui(self):
        """Create the modern GUI layout with a fixed header and scrollable content area."""
        header_frame = ttk.Frame(self.root, style="TFrame", padding=(15, 15, 15, 0))
        header_frame.pack(fill=tk.X)

        canvas_shell = ttk.Frame(self.root, style="TFrame")
        canvas_shell.pack(fill=tk.BOTH, expand=True, padx=15, pady=(10, 0))

        canvas = tk.Canvas(canvas_shell, bg=self.colors['bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        main_container = ttk.Frame(canvas, style="TFrame", padding=(15, 15, 15, 0))
        canvas_window = canvas.create_window((0, 0), window=main_container, anchor="nw")

        self.canvas = canvas
        self.scrollbar = scrollbar
        self.canvas_shell = canvas_shell
        self.scrollbar_visible = True

        def configure_scroll_region(event=None):
            bbox = canvas.bbox("all")
            if not bbox:
                canvas.configure(scrollregion=(0, 0, 0, 0))
                if self.scrollbar_visible:
                    scrollbar.pack_forget()
                    self.scrollbar_visible = False
                return

            x1, y1, x2, y2 = bbox
            content_height = max(0, y2 - y1)
            viewport_height = max(1, canvas.winfo_height())
            canvas.configure(scrollregion=(x1, y1, x2, y2))

            needs_scrollbar = content_height > viewport_height + 1
            if needs_scrollbar and not self.scrollbar_visible:
                scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                self.scrollbar_visible = True
            elif not needs_scrollbar:
                if self.scrollbar_visible:
                    scrollbar.pack_forget()
                    self.scrollbar_visible = False
                canvas.yview_moveto(0)

        def configure_canvas_width(event):
            canvas.itemconfigure(canvas_window, width=event.width)
            configure_scroll_region()

        main_container.bind("<Configure>", configure_scroll_region)
        canvas.bind("<Configure>", configure_canvas_width)
        self.update_scrollbar_visibility = configure_scroll_region
        self.bind_vertical_mousewheel(canvas)
        
        # Header
        
        title_label = ttk.Label(header_frame, text="🐾Sugoi Hook v0.6x", 
                               font=('Segoe UI', 18, 'bold'),
                               foreground=self.colors['primary'])
        title_label.pack(side=tk.LEFT)
        
        self.engine_var = tk.StringVar(value=self.current_engine)
        
        # Content area with a responsive selection row
        content_frame = ttk.Frame(main_container)
        content_frame.pack(fill=tk.BOTH, expand=True)
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=0)  # Process + Hook selection area
        content_frame.rowconfigure(1, weight=0)  # Plugins card
        content_frame.rowconfigure(2, weight=1)  # Output card

        self.selection_cards_frame = ttk.Frame(content_frame)
        self.selection_cards_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        self.selection_cards_frame.columnconfigure(0, weight=1)
        self.selection_cards_frame.columnconfigure(1, weight=1)
        
        # === PROCESS SELECTION CARD ===
        self.create_process_card(self.selection_cards_frame)
        
        # === HOOK SELECTION CARD ===
        self.create_hook_card(self.selection_cards_frame)
        self.update_selection_cards_layout()
        
        # === PLUGINS CARD ===
        self.create_plugins_card(content_frame)
        
        # === TEXT OUTPUT CARD ===
        self.create_output_card(content_frame)
        

        self.configure_mousewheel_routing(main_container)
        
    def bind_vertical_mousewheel(self, widget):
        """Bind mouse wheel scrolling to a specific widget only."""
        widget.bind("<MouseWheel>", lambda event, target=widget: self.on_mousewheel_scroll(event, target))

    def bind_page_mousewheel(self, widget):
        """Bind mouse wheel scrolling to the page scrollbar for non-scrollable widgets."""
        widget.bind("<MouseWheel>", lambda event: self.on_mousewheel_scroll(event, self.canvas) if self.canvas else None)

    def configure_mousewheel_routing(self, widget):
        """Route wheel input to local scrollable widgets or the page fallback elsewhere."""
        local_scroll_widgets = {
            getattr(self, 'process_tree', None),
            getattr(self, 'hook_tree', None),
            getattr(self, 'plugins_tree', None),
            getattr(self, 'event_text', None),
            getattr(self, 'output_text', None),
            self.canvas,
        }

        if widget not in local_scroll_widgets:
            self.bind_page_mousewheel(widget)

        for child in widget.winfo_children():
            self.configure_mousewheel_routing(child)

    def on_mousewheel_scroll(self, event, widget):
        """Scroll only the intended widget."""
        try:
            widget.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"
        except Exception:
            return None

    def create_section_header(self, parent, section_key, title_text, title_style="Title.TLabel"):
        """Create a reusable section header with a left-side collapse toggle."""
        header_frame = ttk.Frame(parent)
        header_frame.columnconfigure(1, weight=1)

        toggle_btn = ttk.Button(
            header_frame,
            text="▾",
            style="Disclosure.TButton",
            command=lambda key=section_key: self.toggle_section(key)
        )
        toggle_btn.grid(row=0, column=0, sticky=tk.W, padx=(2, 2))
        setattr(self, f"{section_key}_toggle_btn", toggle_btn)

        ttk.Label(header_frame, text=title_text, style=title_style).grid(row=0, column=1, sticky=tk.W)
        return header_frame

    def toggle_section(self, section_key, collapsed=None):
        """Show or hide a section body and update its disclosure button."""
        body_attr = f"{section_key}_body_frame"
        toggle_attr = f"{section_key}_toggle_btn"
        state_attr = f"{section_key}_section_collapsed"

        if not hasattr(self, body_attr) or not hasattr(self, toggle_attr):
            return

        if collapsed is None:
            collapsed = not getattr(self, state_attr)

        body = getattr(self, body_attr)
        toggle_btn = getattr(self, toggle_attr)

        setattr(self, state_attr, collapsed)
        if collapsed:
            body.grid_remove()
            toggle_btn.config(text="▸")
        else:
            body.grid()
            toggle_btn.config(text="▾")

        if section_key in ('process', 'hook'):
            self.update_selection_cards_layout()

        if hasattr(self, 'update_scrollbar_visibility'):
            self.root.after(50, self.update_scrollbar_visibility)

        if section_key in ('process', 'hook', 'plugins'):
            if self.is_compact_window_layout():
                self.root.after(80, self.restore_compact_window_geometry)
            elif not collapsed:
                self.root.after(80, self.restore_full_window_geometry)

    def toggle_process_section(self, collapsed=None):
        """Compatibility wrapper for the generalized section toggle."""
        self.toggle_section('process', collapsed)

    def toggle_hook_section(self, collapsed=None):
        """Compatibility wrapper for the generalized section toggle."""
        self.toggle_section('hook', collapsed)

    def update_selection_cards_layout(self):
        """Lay out Process and Hook cards side by side only when both are collapsed."""
        if not hasattr(self, 'process_card') or not hasattr(self, 'hook_card'):
            return
        if not hasattr(self, 'selection_cards_frame'):
            return

        both_collapsed = self.process_section_collapsed and self.hook_section_collapsed

        if both_collapsed:
            self.process_card.grid_configure(row=0, column=0, columnspan=1, padx=(0, 6), pady=(0, 0), sticky=(tk.W, tk.E, tk.N, tk.S))
            self.hook_card.grid_configure(row=0, column=1, columnspan=1, padx=(6, 0), pady=(0, 0), sticky=(tk.W, tk.E, tk.N, tk.S))
        else:
            self.process_card.grid_configure(row=0, column=0, columnspan=2, padx=(0, 0), pady=(0, 12), sticky=(tk.W, tk.E, tk.N, tk.S))
            self.hook_card.grid_configure(row=1, column=0, columnspan=2, padx=(0, 0), pady=(0, 0), sticky=(tk.W, tk.E, tk.N, tk.S))

    def create_process_card(self, parent):
        """Create the process selection card"""
        card = ttk.Frame(parent, style="Card.TFrame", padding=12)
        self.process_card = card
        card.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 12), padx=(0, 6))
        card.columnconfigure(0, weight=1)
        
        # Card header
        header = self.create_section_header(card, 'process', "🎮 1. Select Process")
        header.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        header.columnconfigure(2, weight=0)

        self.process_header_spacer = ttk.Button(
            header,
            text="",
            style="TButton",
            state='disabled'
        )
        self.process_header_spacer.grid(row=0, column=2, sticky=tk.E)

        self.process_body_frame = ttk.Frame(card)
        self.process_body_frame.grid(row=1, column=0, sticky=(tk.W, tk.E))
        self.process_body_frame.columnconfigure(0, weight=1)
        
        # Toolbar row
        toolbar_frame = ttk.Frame(self.process_body_frame)
        toolbar_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 4))

        ttk.Button(toolbar_frame, text="🔄 Refresh", command=self.refresh_processes,
                  style="Secondary.TButton").pack(side=tk.LEFT, padx=(0, 5))

        ttk.Button(toolbar_frame, text="📂 Browse for EXE", 
                  command=self.browse_and_attach_exe,
                  style="Secondary.TButton").pack(side=tk.LEFT, padx=(0, 5))

        ttk.Button(toolbar_frame, text="💾 Game Profiles", 
                  command=self.open_profile_manager,
                  style="Secondary.TButton").pack(side=tk.LEFT)

        # Search row
        search_frame = ttk.Frame(self.process_body_frame)
        search_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        search_frame.columnconfigure(0, weight=1)
        
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.grid(row=0, column=0, sticky=(tk.W, tk.E))
        search_entry.insert(0, "🔍 Search processes...")
        search_entry.bind('<FocusIn>', lambda e: search_entry.delete(0, tk.END) if search_entry.get() == "🔍 Search processes..." else None)
        
        # Process list
        list_frame = ttk.Frame(self.process_body_frame)
        list_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        columns = ('pid', 'arch', 'name')
        self.process_tree = ttk.Treeview(list_frame, columns=columns, show='tree headings', height=3)
        self.process_tree_default_height = 3
        self.process_tree.heading('#0', text='')
        self.process_tree.heading('pid', text='PID')
        self.process_tree.heading('arch', text='Arch')
        self.process_tree.heading('name', text='Process Name')
        
        self.process_tree.column('#0', width=self.scale(28), anchor='center', stretch=False)
        self.process_tree.column('pid', width=self.scale(58), minwidth=self.scale(52), anchor='center', stretch=False)
        self.process_tree.column('arch', width=self.scale(52), minwidth=self.scale(48), anchor='center', stretch=False)
        self.process_tree.column('name', width=self.scale(320), minwidth=self.scale(180), anchor='w', stretch=True)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.process_tree.yview)
        self.process_tree.configure(yscrollcommand=scrollbar.set)
        
        self.process_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # Now set up the search trace after process_tree is created
        self.search_var.trace('w', lambda *args: self.filter_processes())
        
        # Enable double-click to attach
        self.process_tree.bind('<Double-Button-1>', lambda e: self.attach_process())
        self.bind_vertical_mousewheel(self.process_tree)
        
        # Action buttons
        action_frame = ttk.Frame(card)
        action_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(10, 0))
        action_frame.columnconfigure(0, weight=1)

        self.status_label = ttk.Label(action_frame, text="● Not attached", 
                                      style="Status.TLabel",
                                      foreground=self.colors['text_dim'])
        self.status_label.grid(row=0, column=0, sticky=tk.W)

        self.detach_btn = ttk.Button(
            action_frame,
            text="⏹️ Detach",
            command=self.detach_process,
            style="Danger.TButton",
            state='disabled'
        )
        self.detach_btn.grid(row=0, column=1, sticky=tk.E, padx=(0, 8))

        self.attach_btn = ttk.Button(
            action_frame,
            text="➡️ Attach Selected",
            command=self.attach_process,
            style="TButton"
        )
        self.attach_btn.grid(row=0, column=2, sticky=tk.E)
        
    def create_hook_card(self, parent):
        """Create the hook selection card"""
        card = ttk.Frame(parent, style="Card.TFrame", padding=12)
        self.hook_card = card
        card.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 12), padx=(6, 0))
        card.columnconfigure(0, weight=1)
        
        # Card header
        header_frame = self.create_section_header(card, 'hook', "🎯 2. Select Hook")
        header_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        header_frame.columnconfigure(2, weight=0)

        self.select_hook_btn = ttk.Button(
            header_frame,
            text="✅ Use Selected Hook",
            command=self.select_hook,
            style="TButton",
            state='disabled'
        )
        self.select_hook_btn.grid(row=0, column=2, sticky=tk.E)

        status_frame = ttk.Frame(card)
        status_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        status_frame.columnconfigure(0, weight=1)

        self.hook_status_summary = ttk.Label(
            status_frame,
            text="Not attached | Engine: Luna",
            style="Status.TLabel",
            foreground=self.colors['text_dim']
        )
        self.hook_status_summary.grid(row=0, column=0, sticky=tk.W)

        self.hook_active_label = ttk.Label(
            status_frame,
            text="Current hook: none selected",
            style="Status.TLabel",
            foreground=self.colors['text_dim']
        )
        self.hook_active_label.grid(row=1, column=0, sticky=tk.W)

        self.hook_concat_label = ttk.Label(
            status_frame,
            text="Concatenation: inactive",
            style="Status.TLabel",
            foreground=self.colors['text_dim']
        )
        self.hook_concat_label.grid(row=2, column=0, sticky=tk.W)

        self.hook_profile_label = ttk.Label(
            status_frame,
            text="Saved profile: none",
            style="Status.TLabel",
            foreground=self.colors['text_dim']
        )
        self.hook_profile_label.grid(row=3, column=0, sticky=tk.W)

        self.hook_last_action_label = ttk.Label(
            status_frame,
            text="Last action: waiting for attachment",
            style="Status.TLabel",
            foreground=self.colors['text_dim']
        )
        self.hook_last_action_label.grid(row=4, column=0, sticky=tk.W)

        self.hook_body_frame = ttk.Frame(card)
        self.hook_body_frame.grid(row=2, column=0, sticky=(tk.W, tk.E))
        self.hook_body_frame.columnconfigure(0, weight=1)
        
        # Hook list
        list_frame = ttk.Frame(self.hook_body_frame)
        list_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        columns = ('id', 'function', 'preview')
        self.hook_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=3)
        self.hook_tree_default_height = 3
        self.hook_tree.heading('id', text='ID')
        self.hook_tree.heading('function', text='Function')
        self.hook_tree.heading('preview', text='Text Preview')
        
        self.hook_tree.column('id', width=self.scale(44), minwidth=self.scale(40), anchor='center', stretch=False)
        self.hook_tree.column('function', width=self.scale(210), minwidth=self.scale(140), anchor='w', stretch=False)
        self.hook_tree.column('preview', width=self.scale(520), minwidth=self.scale(260), anchor='w', stretch=True)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.hook_tree.yview)
        h_scrollbar = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.hook_tree.xview)
        self.hook_tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        self.hook_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        h_scrollbar.grid(row=1, column=0, sticky=(tk.W, tk.E))
        
        # Enable double-click to select hook
        self.hook_tree.bind('<Double-Button-1>', lambda e: self.select_hook())
        self.hook_tree.bind('<Button-3>', self.show_hook_context_menu)
        self.bind_vertical_mousewheel(self.hook_tree)
        
        # Manual hook input section
        manual_hook_frame = ttk.Frame(self.hook_body_frame)
        manual_hook_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(8, 0))
        manual_hook_frame.columnconfigure(1, weight=1)
        
        ttk.Label(manual_hook_frame, text="Manual Hook:", 
                 font=('Segoe UI', 9, 'bold'),
                 foreground=self.colors['accent']).grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        
        self.manual_hook_entry = ttk.Entry(manual_hook_frame)
        self.manual_hook_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        self.manual_hook_entry.insert(0, "e.g., HB4@0 or HS-4@12345")
        self.manual_hook_entry.bind('<FocusIn>', lambda e: self.manual_hook_entry.delete(0, tk.END) 
                                    if self.manual_hook_entry.get().startswith("e.g.,") else None)
        self.manual_hook_entry.bind('<Return>', lambda e: self.attach_manual_hook())
        
        self.attach_manual_hook_btn = ttk.Button(manual_hook_frame, text="🔗 Attach Hook", 
                                                 command=self.attach_manual_hook,
                                                 style="Secondary.TButton",
                                                 state='disabled')
        self.attach_manual_hook_btn.grid(row=0, column=2)
        
        # Help button for hook syntax
        help_btn = ttk.Button(manual_hook_frame, text="❓", 
                             command=self.show_hook_help,
                             style="Secondary.TButton",
                             width=3)
        help_btn.grid(row=0, column=3, padx=(5, 0))

        self.hook_tree.bind('<<TreeviewSelect>>', lambda e: self.update_hook_action_state())
        self.update_hook_status_panel()
        self.update_hook_action_state()
        
    def create_plugins_card(self, parent):
        """Create the plugins management card"""
        card = ttk.Frame(parent, style="Card.TFrame", padding=12)
        card.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        card.columnconfigure(0, weight=1)
        
        # Card header
        header_frame = self.create_section_header(card, 'plugins', "🔌 Plugins")
        header_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 4))
        
        # Plugin action buttons
        btn_frame = ttk.Frame(header_frame)
        btn_frame.grid(row=0, column=2, sticky=tk.E)
        
        # Show active plugins count
        self.plugins_count_label = ttk.Label(btn_frame, 
                                             text=f"Active: {len(self.active_plugins)} plugins",
                                             style="Status.TLabel",
                                             foreground=self.colors['text_dim'])
        self.plugins_count_label.pack(side=tk.LEFT, padx=(0, 10))
        
        
        ttk.Button(btn_frame, text="📂 Open Folder", 
                  command=self.open_plugins_folder,
                  style="Secondary.TButton").pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Button(btn_frame, text="🔄 Refresh", 
                  command=self.reload_plugins,
                  style="Secondary.TButton").pack(side=tk.LEFT)
        
        self.plugins_body_frame = ttk.Frame(card)
        self.plugins_body_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.plugins_body_frame.columnconfigure(0, weight=1)

        controls_frame = ttk.Frame(self.plugins_body_frame)
        controls_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 8))

        self.plugin_toggle_btn = ttk.Button(controls_frame, text="Toggle Active", command=self.toggle_selected_plugin, style="Secondary.TButton")
        self.plugin_toggle_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.plugin_configure_btn = ttk.Button(controls_frame, text="Configure", command=self.configure_selected_plugin, style="Secondary.TButton")
        self.plugin_configure_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.plugin_move_up_btn = ttk.Button(controls_frame, text="Move Up", command=lambda: self.move_selected_plugin(-1), style="Secondary.TButton")
        self.plugin_move_up_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.plugin_move_down_btn = ttk.Button(controls_frame, text="Move Down", command=lambda: self.move_selected_plugin(1), style="Secondary.TButton")
        self.plugin_move_down_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.plugin_controls_hint = ttk.Label(controls_frame, text="Tip: Use buttons for precise ordering. Drag still works.", style="Status.TLabel", foreground=self.colors['text_dim'])
        self.plugin_controls_hint.pack(side=tk.RIGHT)

        # Plugins list
        list_frame = ttk.Frame(self.plugins_body_frame)
        list_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        columns = ('status', 'name', 'version', 'description', 'actions')
        self.plugins_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=7)
        self.plugins_tree.heading('status', text='Status')
        self.plugins_tree.heading('name', text='Plugin Name')
        self.plugins_tree.heading('version', text='Version')
        self.plugins_tree.heading('description', text='Description')
        self.plugins_tree.heading('actions', text='Actions')
        
        self.plugins_tree.column('status', width=self.scale(80), minwidth=self.scale(80), anchor='center', stretch=False)
        self.plugins_tree.column('name', width=self.scale(150), minwidth=self.scale(120), anchor='center', stretch=False)
        self.plugins_tree.column('version', width=self.scale(60), minwidth=self.scale(50), anchor='center', stretch=False)
        self.plugins_tree.column('description', width=self.scale(350), minwidth=self.scale(180), anchor='center', stretch=True)
        self.plugins_tree.column('actions', width=self.scale(100), minwidth=self.scale(100), anchor='center', stretch=False)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.plugins_tree.yview)
        self.plugins_tree.configure(yscrollcommand=scrollbar.set)
        
        self.plugins_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # Enable double-click to toggle plugin
        self.plugins_tree.bind('<Double-Button-1>', lambda e: self.toggle_selected_plugin())
        
        # Enable single-click on Actions column for configure button
        self.plugins_tree.bind('<Button-1>', self.on_plugin_click)
        
        # Enable right-click context menu
        self.plugins_tree.bind('<Button-3>', self.show_plugin_context_menu)
        
        # Enable Drag and Drop for reordering
        self.plugins_tree.bind('<B1-Motion>', self.on_plugin_drag_motion)
        self.plugins_tree.bind('<ButtonRelease-1>', self.on_plugin_drag_release)
        
        self.plugins_tree.bind('<<TreeviewSelect>>', lambda e: self.update_plugin_action_buttons())
        self.bind_vertical_mousewheel(self.plugins_tree)

        # Populate the plugins list
        self.refresh_plugins_list()
        self.toggle_section('plugins', self.plugins_section_collapsed)
        self.update_plugin_action_buttons()
    
    def on_plugin_click(self, event):
        """Handle clicks on plugin tree, especially on Actions column"""
        # Identify which item and column was clicked
        item = self.plugins_tree.identify_row(event.y)
        column = self.plugins_tree.identify_column(event.x)
        
        if not item:
            return
        
        # Check if Actions column was clicked (column #5, index starts at #1)
        if column == '#5':  # Actions column
            # Get the item data
            item_data = self.plugins_tree.item(item)
            actions_text = item_data['values'][4]  # Actions is the 5th column (index 4)
            
            # If it has the configure button text, open configuration
            if actions_text == "⚙️ Configure":
                # Select the item
                self.plugins_tree.selection_set(item)
                # Open configuration dialog
                self.configure_selected_plugin()
                return "break"  # Prevent further processing
        else:
            # For other columns, handle drag start for reordering
            if item:
                self.drag_start_item = item
    
    def on_plugin_drag_start(self, event):
        """Handle start of plugin drag"""
        item = self.plugins_tree.identify_row(event.y)
        if item:
            self.drag_start_item = item
            
    def on_plugin_drag_motion(self, event):
        """Handle feedback during plugin drag"""
        # Just ensure we track the drag
        pass
    
    def on_plugin_drag_release(self, event):
        """Handle end of plugin drag (drop)"""
        if not hasattr(self, 'drag_start_item') or not self.drag_start_item:
            return
            
        target_item = self.plugins_tree.identify_row(event.y)
        if target_item and target_item != self.drag_start_item:
            try:
                # Get index of target
                target_index = self.plugins_tree.index(target_item)
                
                # Move item to the target index
                self.plugins_tree.move(self.drag_start_item, '', target_index)
                
                # Update plugin_order based on the new visual order
                new_order = []
                for item in self.plugins_tree.get_children():
                    # Get filename from hidden text attribute
                    filename = self.plugins_tree.item(item, 'text')
                    if filename:
                        new_order.append(filename)
                
                # Update stored order
                self.plugin_order = new_order
                self.save_plugins_config()
                
            except Exception:
                pass
                
        self.drag_start_item = None
    
    def reload_plugins(self):
        """Reload all plugins from the plugins folder"""
        active_plugins = list(self.active_plugins)
        with self.output_processing_lock:
            self.invalidate_output_processing(clear_pending=True)
            self.shutdown_plugin_instances()
            self.active_plugins = active_plugins
            self.plugins.clear()
            self.discover_plugins()
        self.refresh_plugins_list()
        
        # Update count label
        if hasattr(self, 'plugins_count_label'):
            self.plugins_count_label.config(text=f"Active: {len(self.active_plugins)} plugins")
    
    def create_output_card(self, parent):
        """Create the text output card"""
        card = ttk.Frame(parent, style="Card.TFrame", padding=12)
        card.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 15))
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)
        
        # Card header
        header_frame = self.create_section_header(card, 'output', "📝 Session Output")
        header_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        
        # Action buttons
        action_frame = ttk.Frame(header_frame)
        action_frame.grid(row=0, column=2, sticky=tk.E)
        
        ttk.Button(action_frame, text="💾 Save to File", 
                  command=self.save_to_file,
                  style="Secondary.TButton").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(action_frame, text="🗑️ Clear", 
                  command=self.clear_output,
                  style="Secondary.TButton").pack(side=tk.LEFT)
        
        self.output_body_frame = ttk.Frame(card)
        self.output_body_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.output_body_frame.columnconfigure(0, weight=1)
        self.output_body_frame.rowconfigure(1, weight=1)
        self.output_body_frame.rowconfigure(3, weight=1)

        events_header = self.create_section_header(self.output_body_frame, 'events', "Session Events", title_style="Status.TLabel")
        events_header.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 4))

        self.events_body_frame = ttk.Frame(self.output_body_frame)
        self.events_body_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        self.events_body_frame.columnconfigure(0, weight=1)
        self.events_body_frame.rowconfigure(0, weight=1)

        self.event_text = tk.Text(
            self.events_body_frame,
            wrap=tk.WORD,
            bg=self.colors['bg'],
            fg=self.colors['text_dim'],
            insertbackground=self.colors['primary'],
            selectbackground=self.colors['primary'],
            selectforeground=self.colors['bg'],
            font=('Consolas', 9),
            borderwidth=0,
            padx=10,
            pady=8,
            state='disabled',
            height=1
        )
        self.event_scrollbar = ttk.Scrollbar(self.events_body_frame, orient=tk.VERTICAL, command=self.event_text.yview)
        self.event_text.configure(yscrollcommand=self.event_scrollbar.set)
        self.event_text.grid(row=0, column=0, sticky=(tk.W, tk.E))
        self.event_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.event_scrollbar.grid_remove()
        self.event_text_default_height = 1
        self.bind_vertical_mousewheel(self.event_text)

        extracted_header = self.create_section_header(self.output_body_frame, 'extracted', "Extracted Text", title_style="Status.TLabel")
        extracted_header.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 4))

        self.extracted_body_frame = ttk.Frame(self.output_body_frame)
        self.extracted_body_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.extracted_body_frame.columnconfigure(0, weight=1)
        self.extracted_body_frame.rowconfigure(0, weight=1)

        self.output_text = scrolledtext.ScrolledText(
            self.extracted_body_frame, wrap=tk.WORD,
            bg=self.colors['bg'],
            fg=self.colors['fg'],
            insertbackground=self.colors['primary'],
            selectbackground=self.colors['primary'],
            selectforeground=self.colors['bg'],
            font=('Consolas', 10),
            borderwidth=0,
            padx=10, pady=10,
            state='disabled',
            height=8
        )
        self.output_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.output_text_default_height = 8
        self.bind_vertical_mousewheel(self.output_text)

    def create_footer(self, parent):
        """Create the footer with action buttons"""
        footer = ttk.Frame(parent)
        footer.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(5,0))
        
        ttk.Button(footer, text="🗑️ Clear", command=self.clear_output,
                  style="Secondary.TButton").pack(side=tk.LEFT, padx=(0, 10))
        
        self.detach_btn = ttk.Button(footer, text="⏹️ Detach", 
                                     command=self.detach_process, 
                                     style="Danger.TButton",
                                     state='disabled')
        self.detach_btn.pack(side=tk.LEFT)
        
        if TRAY_AVAILABLE:
            ttk.Button(footer, text="🔽 Minimize to Tray", command=self.hide_to_tray,
                      style="Secondary.TButton").pack(side=tk.RIGHT)
        
    def should_exclude_process(self, proc_name, proc_path=None):
        """
        Advanced filtering to exclude system processes and bloatware
        Returns True if process should be excluded
        """
        name_lower = proc_name.lower()
        
        # 1. Check exact executable name matches
        if name_lower in self.excluded_executables:
            return True
        
        # 2. Check if it's in a system directory
        if proc_path:
            path_lower = proc_path.lower()
            for sys_dir in self.system_dirs:
                if path_lower.startswith(sys_dir):
                    return True
        
        # 3. Check system process patterns
        for pattern in self.system_process_patterns:
            if pattern in name_lower:
                return True
        
        # 4. Check bloatware patterns
        for pattern in self.bloatware_patterns:
            if pattern in name_lower:
                return True
        
        # 5. Filter processes without window titles (likely background services)
        # This will be checked in refresh_processes
        
        return False
    
    def has_visible_window(self, pid):
        """Check if process has a visible window (heuristic for user applications)"""
        try:
            def enum_windows_callback(hwnd, windows):
                if win32gui.IsWindowVisible(hwnd):
                    _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
                    if window_pid == pid:
                        title = win32gui.GetWindowText(hwnd)
                        # Only count windows with actual titles
                        if title and len(title) > 0:
                            windows.append((hwnd, title))
                return True
            
            windows = []
            win32gui.EnumWindows(enum_windows_callback, windows)
            return len(windows) > 0
        except:
            # If we can't check, assume it might be valid
            return True
    
    def get_process_icon(self, pid):
        """Extract high-quality icon from process executable"""
        if pid in self.process_icons:
            return self.process_icons[pid]
        
        try:
            proc = psutil.Process(pid)
            exe_path = proc.exe()
            
            # Try to extract both large and small icons
            large, small = win32gui.ExtractIconEx(exe_path, 0)
            
            # Prefer large icon for better quality, fall back to small if needed
            icon_handle = large[0] if large else (small[0] if small else None)
            
            if icon_handle:
                # Use larger icon size for better quality (32x32)
                icon_size = 32
                
                hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
                hbmp = win32ui.CreateBitmap()
                hbmp.CreateCompatibleBitmap(hdc, icon_size, icon_size)
                hdc = hdc.CreateCompatibleDC()
                hdc.SelectObject(hbmp)
                
                # Draw icon with transparent background support
                hdc.DrawIcon((0, 0), icon_handle)
                
                bmpstr = hbmp.GetBitmapBits(True)
                img = Image.frombuffer('RGB', (icon_size, icon_size), bmpstr, 'raw', 'BGRX', 0, 1)
                
                # Resize with high-quality resampling to scaled size for better clarity
                scaled_size = self.scale(24)
                img = img.resize((scaled_size, scaled_size), Image.Resampling.LANCZOS)
                
                # Add subtle rounded corners for modern look
                mask = Image.new('L', (scaled_size, scaled_size), 0)
                draw = ImageDraw.Draw(mask)
                draw.rounded_rectangle([(0, 0), (scaled_size-1, scaled_size-1)], radius=self.scale(3), fill=255)
                img.putalpha(mask)
                
                photo = ImageTk.PhotoImage(img)
                self.process_icons[pid] = photo
                
                # Clean up icon handles
                if large:
                    win32gui.DestroyIcon(large[0])
                if small:
                    win32gui.DestroyIcon(small[0])
                
                return photo
        except Exception as e:
            # Silently fail for processes without accessible icons
            pass
        
        return None
    
    def get_process_architecture(self, pid):
        """Determine if a process is 32-bit or 64-bit"""
        try:
            if sys.platform == 'win32':
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x1000, False, pid)
                if handle:
                    is_wow64 = ctypes.c_bool()
                    if kernel32.IsWow64Process(handle, ctypes.byref(is_wow64)):
                        kernel32.CloseHandle(handle)
                        return "x86" if is_wow64.value else "x64"
                    kernel32.CloseHandle(handle)
        except:
            pass
        return "x86"
    
    def refresh_processes(self):
        """Refresh the list of running processes with advanced filtering"""
        self.process_tree.delete(*self.process_tree.get_children())
        self.all_processes = []
        self.process_icons.clear()
        
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                pid = proc.info['pid']
                name = proc.info['name']
                exe_path = proc.info.get('exe', '')
                
                # Skip very low PIDs (system processes)
                if pid < 100:
                    continue
                
                # Apply advanced filtering
                if self.should_exclude_process(name, exe_path):
                    continue
                
                # Additional heuristic: check if process has visible windows
                # This helps filter out background services and daemons
                if not self.has_visible_window(pid):
                    continue
                
                arch = self.get_process_architecture(pid)
                icon = self.get_process_icon(pid)
                self.all_processes.append((pid, arch, name, icon))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        self.filter_processes()
    
    def filter_processes(self):
        """Filter processes based on search term"""
        self.process_tree.delete(*self.process_tree.get_children())
        search_term = self.search_var.get().lower()
        if search_term == "🔍 search processes...":
            search_term = ""
        
        for pid, arch, name, icon in self.all_processes:
            if search_term in name.lower() or search_term in str(pid):
                self.process_tree.insert('', tk.END, text='', values=(pid, arch, name), 
                                        image=icon if icon else '')
    
    def attach_process(self):
        """Attach to the selected process"""
        selection = self.process_tree.selection()
        if not selection:
            self.notify_user("Select a process to attach.", level='warning')
            return
        
        item = self.process_tree.item(selection[0])
        pid, arch, name = item['values']
        
        # Luna-only build: always attach through Luna
        cli_path = self.luna_x86_path if arch == "x86" else self.luna_x64_path
        if not cli_path.exists():
            cli_path = self.luna_x86_path
        
        try:
            # Get the directory containing the CLI executable
            cli_dir = cli_path.parent
            
            # When running as compiled executable, we need to ensure DLLs are accessible
            # Set up environment to include the CLI directory in PATH
            env = os.environ.copy()
            if getattr(sys, 'frozen', False):
                # Add the CLI directory to PATH so DLLs can be found
                env['PATH'] = str(cli_dir) + os.pathsep + env.get('PATH', '')
            
            # Create process with CREATE_NO_WINDOW flag to hide console
            import ctypes
            CREATE_NO_WINDOW = 0x08000000
            
            self.cli_process = subprocess.Popen(
                [str(cli_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-16-le',
                errors='ignore',
                bufsize=1,
                cwd=str(cli_dir),
                env=env,
                creationflags=CREATE_NO_WINDOW
            )
            
            self.cli_process.stdin.write(f"attach -P{pid}\n")
            self.cli_process.stdin.flush()
            
            self.attached_pid = pid
            self.status_label.config(text=f"● Attached to {name}", 
                                    foreground=self.colors['success'])
            
            self.detach_btn.config(state='normal')
            self.update_hook_action_state()
            
            self.is_reading = True
            with self.hooks_lock:
                self.hooks.clear()
            self.hook_tree.delete(*self.hook_tree.get_children())
            
            threading.Thread(target=self.read_cli_output, daemon=True).start()
            
            self.append_event(f"✓ Attached to {name} (PID: {pid})\n")
            self.append_event("⏳ Waiting for hooks... Please start the game and click on a dialogue.\n\n")
            self.update_hook_status_panel(f"attached to {name}")
            self.notify_user(f"Attached to {name}.", level='success')
            self.toggle_section('process', True)
            if self.get_hook_concatenation_state().get('active'):
                self.toggle_section('hook', True)
            
            # Check for saved game profile and prepare auto-hook
            self.check_and_load_hook_profile()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to attach:\n{str(e)}")
            self.status_label.config(text="● Attachment failed", 
                                    foreground=self.colors['secondary'])
            self.update_hook_status_panel("attachment failed")
    
    def attach_manual_hook(self):
        """Attach a manual hook using hook code"""
        if not self.attached_pid:
            self.notify_user("Attach to a process first.", level='warning')
            return
        
        hook_code = self.manual_hook_entry.get().strip()
        
        # Check if it's the placeholder text
        if not hook_code or hook_code.startswith("e.g.,"):
            self.notify_user("Enter a valid hook code.", level='warning')
            return
        
        # Basic validation of hook code format
        if not self.validate_hook_code(hook_code):
            messagebox.showwarning("Invalid Hook Code", 
                "Invalid hook code format.\n\n"
                "Hook codes should start with H or R followed by type and parameters.\n"
                "Examples:\n"
                "  HB4@0\n"
                "  HS-4@12345\n"
                "  HQ@401000:user32.dll\n\n"
                "Click the ❓ button for more information.")
            return
        
        try:
            # Send hook code to CLI
            command = f"{hook_code} -P{self.attached_pid}\n"
            self.cli_process.stdin.write(command)
            self.cli_process.stdin.flush()
            
            self.append_event(f"🔗 Manual hook attached: {hook_code}\n")
            self.append_event("⏳ Waiting for text output...\n\n")
            self.update_hook_status_panel(f"attached manual hook {hook_code}")
            self.notify_user("Manual hook sent. Waiting for text output.", level='success')
            
            # Save manual hook to game profile
            self.save_hook_profile(hook_code=hook_code)
            
            # Clear the entry field
            self.manual_hook_entry.delete(0, tk.END)
            self.manual_hook_entry.insert(0, "e.g., HB4@0 or HS-4@12345")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to attach manual hook:\n{str(e)}")
    
    def validate_hook_code(self, hook_code):
        """Validate hook code format"""
        # Basic validation - hook codes should start with H or R
        if not hook_code:
            return False
        
        # H-codes (Hook codes) or R-codes (Read codes)
        if hook_code[0] not in ['H', 'R', 'h', 'r']:
            return False
        
        # Should contain @ symbol for address
        if '@' not in hook_code:
            return False
        
        return True
    
    def show_hook_help(self):
        """Show help dialog for hook code syntax"""
        help_text = """
HOOK CODE SYNTAX GUIDE

═══════════════════════════════════════════════════════

H-CODES (Hook Codes)
Format: H{type}{flags}{data_offset}[*deref_offset][:split_offset]@address[:module[:function]]

TYPE CHARACTERS:
  A - ANSI text, big endian, single character
  B - ANSI text, single character
  W - Unicode text, single character
  H - Unicode text with hex dump, single character
  S - ANSI string
  Q - Unicode string
  V - UTF-8 string
  M - Unicode string with hex dump

FLAGS:
  F - Full string capture
  N - No context
  <number>< - Null length specifier
  <number># - Codepage specifier
  <hex>+ - Padding bytes

EXAMPLES:
  HB4@0                    Hook at address 0, ANSI single char, offset 4
  HS-4@12345               Hook at 0x12345, ANSI string, offset -4
  HQ@401000:user32.dll     Hook in user32.dll at offset 0x401000, Unicode string
  HSN-4*0@12345            Hook with no context, ANSI string, offset -4

═══════════════════════════════════════════════════════

R-CODES (Read Codes)
Format: R{type}[null_length<][codepage#]@address

TYPE CHARACTERS:
  S - ANSI string
  Q - Unicode string
  V - UTF-8 string
  M - Unicode string with hex dump

EXAMPLES:
  RS@401000               Read ANSI string at address 0x401000
  RQ@401000               Read Unicode string at address 0x401000
  RV@402000               Read UTF-8 string at address 0x402000

═══════════════════════════════════════════════════════

TIPS:
• Use hex addresses (e.g., 0x401000 or just 401000)
• Negative offsets are allowed (e.g., -4)
• Module names are optional but helpful for portability
• Start with simple hooks (HB4@0) and adjust as needed
• Monitor the output to see if the hook captures text correctly

For more information, refer to the Luna Hook documentation and current community hook guides.
"""
        
        # Create a custom dialog
        help_window = tk.Toplevel(self.root)
        help_window.title("Hook Code Syntax Help")
        help_window.geometry("700x600")
        help_window.configure(bg=self.colors['bg'])
        
        # Make it modal
        help_window.transient(self.root)
        help_window.grab_set()
        
        # Create text widget with scrollbar
        text_frame = ttk.Frame(help_window, style="Card.TFrame", padding=15)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        text_widget = scrolledtext.ScrolledText(
            text_frame,
            wrap=tk.WORD,
            bg=self.colors['surface'],
            fg=self.colors['fg'],
            font=('Consolas', 9),
            borderwidth=0,
            padx=10,
            pady=10
        )
        text_widget.pack(fill=tk.BOTH, expand=True)
        text_widget.insert(1.0, help_text)
        text_widget.config(state='disabled')
        
        # Close button
        close_btn = ttk.Button(help_window, text="Close", 
                              command=help_window.destroy,
                              style="Secondary.TButton")
        close_btn.pack(pady=(0, 15))
        
        # Center the window
        help_window.update_idletasks()
        x = (help_window.winfo_screenwidth() // 2) - (help_window.winfo_width() // 2)
        y = (help_window.winfo_screenheight() // 2) - (help_window.winfo_height() // 2)
        help_window.geometry(f"+{x}+{y}")
    
    def on_engine_change(self):
        """Luna-only build; engine selection is fixed."""
        self.engine_var.set("luna")
        self.current_engine = "luna"
    
    def route_hook_output(self, hook_id, text, event_sequence):
        with self.output_processing_lock:
            concat_state = self.get_hook_concatenation_state()
            concat_owns_hook = concat_state['active'] and hook_id in concat_state['hook_ids']
            if concat_owns_hook:
                self.mark_hook_event_submitted(hook_id, event_sequence)
                self.append_output(f"[Hook #{hook_id}|{event_sequence}] {text}\n", True, False)
                return 'concatenation'
            if self.selected_hook_id and hook_id == self.selected_hook_id:
                if text:
                    self.mark_hook_event_submitted(hook_id, event_sequence)
                    self.append_output(text + "\n", True, True)
                    return 'selected'
                return None
            if not self.selected_hook_id and not self.silent_auto_launch:
                # Only show hook preview if not in silent auto-launch mode
                self.mark_hook_event_submitted(hook_id, event_sequence)
                self.append_output(f"[Hook #{hook_id}] {text}\n", True, False)
                return 'preview'
        return None

    def read_cli_output(self):
        """Read output from the Luna CLI process."""
        self.read_luna_output()
    
    def read_luna_output(self):
        """Read and parse Luna Hook CLI output"""
        # Luna Hook CLI format: [#ID|context_info] text
        pattern = re.compile(r'^\[#(\d+)\|([^\]]+)\] (.*)$')
        console_pattern = re.compile(r'^\[Console\] (.+)$')
        
        while self.is_reading and self.cli_process:
            try:
                line = self.cli_process.stdout.readline()
                if not line:
                    break
                
                line = line.strip()
                if not line:
                    continue
                
                # Check for console messages
                console_match = console_pattern.match(line)
                if console_match:
                    text_to_process = f"[Console] {console_match.group(1)}\n"
                    self.append_output(text_to_process, True, False)
                    continue
                
                # Check for hook output
                match = pattern.match(line)
                if match:
                    hook_id = match.group(1)
                    context_info = match.group(2)
                    text = match.group(3)
                    
                    # Extract hook name from context (last part before .exe)
                    context_parts = context_info.split(':')
                    if len(context_parts) >= 2:
                        # Try to find a meaningful name from the context
                        thread_name = context_parts[-2] if len(context_parts) > 1 else context_parts[0]
                    else:
                        thread_name = "Unknown"
                    
                    now = time.monotonic()
                    with self.output_processing_lock:
                        with self.hooks_lock:
                            is_new_hook = hook_id not in self.hooks
                            if is_new_hook:
                                self.hooks[hook_id] = {
                                    'id': hook_id,
                                    'function': thread_name,
                                    'context_info': context_info,
                                    'texts': [],
                                    'latest_text': '',
                                    'last_seen_monotonic': 0.0,
                                    'latest_event_sequence': 0,
                                    'last_pipeline_sequence': 0,
                                    'last_processed_sequence': 0,
                                }
                            self.hook_event_sequence += 1
                            event_sequence = self.hook_event_sequence
                            hook_info = self.hooks[hook_id]
                            hook_info['latest_text'] = text
                            hook_info['last_seen_monotonic'] = now
                            hook_info['latest_event_sequence'] = event_sequence
                            hook_info['latest_event_snapshot'] = (text, now, event_sequence)
                            if len(hook_info['texts']) < MAX_HOOK_TEXTS:
                                hook_info['texts'].append(text)
                        self.route_hook_output(hook_id, text, event_sequence)
                    if is_new_hook:
                        self.run_on_ui_thread(self.add_hook_to_list, hook_id, thread_name)
                    
                    # Store text and update preview
                    self.run_on_ui_thread(self.update_hook_preview, hook_id, text)
                
            except Exception:
                break
    
    def add_hook_to_list(self, hook_id, function):
        """Add a hook to the hook list"""
        function_label = self.format_hook_function_label(hook_id, function)
        self.hook_tree.insert('', tk.END, values=(hook_id, function_label, "Waiting for text..."))
        self.update_hook_action_state()
        self.update_hook_status_panel()
        
        # Check if we should auto-select this hook (with longer delay to let all hooks populate)
        # Some games insert many hooks before the correct one appears
        if self.auto_hook_pending and not hasattr(self, '_auto_hook_scheduled'):
            self._auto_hook_scheduled = True
            self._auto_hook_retry_count = 0
            self.root.after(8000, self.attempt_auto_hook)  # Wait 8 seconds for hooks to populate
    
    def update_hook_preview(self, hook_id, current_text=None):
        """Update the preview text for a hook"""
        if hook_id in self.hooks:
            # Use current_text if provided, otherwise fall back to stored texts
            if current_text:
                preview_text = ' '.join(current_text.split())
            else:
                texts = self.hooks[hook_id]['texts']
                if texts and texts[0]:
                    preview_text = ' '.join(texts[0].split())
                else:
                    preview_text = None
            
            # Format the preview
            if preview_text:
                # Limit preview to 80 characters to prevent window breaking
                if len(preview_text) > 80:
                    preview = preview_text[:80] + "..."
                else:
                    preview = preview_text
            else:
                preview = "No text yet"
            
            # Update the tree view - ensure hook_id comparison works correctly
            for item in self.hook_tree.get_children():
                item_values = self.hook_tree.item(item)['values']
                # Convert both to strings for comparison to handle type mismatches
                if str(item_values[0]) == str(hook_id):
                    function_name = self.hooks.get(str(hook_id), {}).get('function', item_values[1])
                    self.hook_tree.item(item, values=(item_values[0], self.format_hook_function_label(hook_id, function_name), preview))
                    break
            self.update_hook_status_panel()
    
    def update_hook_action_state(self):
        """Enable or disable hook actions based on current selection."""
        if hasattr(self, 'select_hook_btn'):
            concat_state = self.get_hook_concatenation_state()
            if concat_state['active']:
                self.select_hook_btn.config(text='🔗 Concatenation Manages Output', state='disabled')
            else:
                state = 'normal' if self.hook_tree.selection() and self.attached_pid else 'disabled'
                self.select_hook_btn.config(text='✅ Use Selected Hook', state=state)

        if hasattr(self, 'attach_manual_hook_btn'):
            self.attach_manual_hook_btn.config(state='normal' if self.attached_pid else 'disabled')

    def select_hook(self):
        """Select a hook to display its output"""
        selection = self.hook_tree.selection()
        if not selection:
            self.notify_user("Select a hook to activate it.", level='warning')
            return
        
        item = self.hook_tree.item(selection[0])
        hook_id = str(item['values'][0])
        
        try:
            self.cli_process.stdin.write(f"select {hook_id}\n")
            self.cli_process.stdin.flush()
            
            self.selected_hook_id = hook_id
            self.clear_output()
            self.append_event(f"✓ Selected Hook {hook_id}\n")
            self.append_event(f"Function: {item['values'][1]}\n")
            self.append_event("─" * 50 + "\n\n")
            
            hook_info = self.get_hooks_snapshot().get(hook_id, {})
            concat_state = self.get_hook_concatenation_state()
            concat_owns_hook = concat_state['active'] and hook_id in concat_state['hook_ids']
            if hook_info.get('texts') and not concat_owns_hook:
                for text in hook_info['texts']:
                    self.append_output(f"{text}\n", True, True)
                self.append_event("\n" + "─" * 50 + "\n\n")
            
            # Save this hook selection to game profile
            self.save_hook_profile(hook_id=hook_id)
            self.update_hook_status_panel(f"selected hook {hook_id}")
            self.notify_user(f"Hook {hook_id} selected.", level='success')
            self.toggle_section('hook', True)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to select hook:\n{str(e)}")

    def show_hook_context_menu(self, event):
        """Show a context menu for hook list actions."""
        try:
            item = self.hook_tree.identify_row(event.y)
            if not item:
                return

            self.hook_tree.selection_set(item)
            item_values = self.hook_tree.item(item).get('values', ())
            if not item_values:
                return

            hook_id = str(item_values[0])
            hook_info = self.hooks.get(hook_id, {})
            context_info = str(hook_info.get('context_info', '')).strip()
            function_name = str(hook_info.get('function', item_values[1] if len(item_values) > 1 else '')).strip()
            concat_selector = self.get_hook_concat_selector_value(hook_id)
            concat_plugin_filename = self.get_plugin_filename_by_name('Hook Concatenation')

            menu = tk.Menu(self.root, tearoff=0, bg=self.colors['surface'], fg=self.colors['fg'])
            menu.add_command(label="Use Selected Hook", command=self.select_hook)
            menu.add_command(
                label="Copy Hook ID",
                command=lambda hook_id=hook_id: self.copy_hook_context_info(hook_id, "hook ID")
            )
            if context_info:
                menu.add_command(
                    label="Copy Luna Context Info",
                    command=lambda context_info=context_info: self.copy_hook_context_info(context_info, "Luna context info")
                )
            if function_name:
                menu.add_command(
                    label="Copy Hook Function Label",
                    command=lambda function_name=function_name: self.copy_hook_context_info(function_name, "hook function label")
                )

            if concat_plugin_filename and concat_selector:
                menu.add_separator()
                menu.add_command(
                    label="Set as Dialogue Hook",
                    command=lambda hook_id=hook_id: self.set_hook_concat_role(hook_id, 'dialogue')
                )
                menu.add_command(
                    label="Set as Prefix Hook",
                    command=lambda hook_id=hook_id: self.set_hook_concat_role(hook_id, 'prefix')
                )

            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def copy_hook_context_info(self, value: str, label: str = "hook value"):
        """Copy hook-related metadata to the clipboard."""
        try:
            if not str(value).strip():
                self.notify_user(f"No {label} available for this hook.", level='warning')
                return
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
            self.root.update()
            self.notify_user(f"Copied {label} to clipboard.", level='success')
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to copy {label}:\n{str(exc)}")

    def get_hook_concat_selector_value(self, hook_id: str) -> str:
        """Return the preferred selector value for hook concatenation."""
        hook_info = self.get_hooks_snapshot().get(str(hook_id), {})
        function_name = str(hook_info.get('function', '')).strip()
        context_info = str(hook_info.get('context_info', '')).strip()
        return function_name or context_info or str(hook_id).strip()

    def resolve_hook_concat_selector(self, selector: str) -> str:
        """Resolve a concat selector to the current session hook ID when possible."""
        normalized_selector = str(selector or '').strip()
        if not normalized_selector:
            return ''
        if normalized_selector.isdigit():
            return normalized_selector

        for hook_id, hook_info in self.get_hooks_snapshot().items():
            context_info = str(hook_info.get('context_info', '')).strip()
            function_name = str(hook_info.get('function', '')).strip()
            if normalized_selector in {context_info, function_name}:
                return str(hook_id)
        return ''

    def filter_hook_concat_selectors(self, selectors, excluded_hook_id: str) -> list[str]:
        """Remove selectors that point at the excluded hook ID and dedupe the remainder."""
        excluded_hook_id = str(excluded_hook_id).strip()
        filtered = []
        seen = set()
        for selector in selectors:
            normalized_selector = str(selector).strip()
            if not normalized_selector:
                continue
            resolved_hook_id = self.resolve_hook_concat_selector(normalized_selector)
            if excluded_hook_id and resolved_hook_id == excluded_hook_id:
                continue
            dedupe_key = resolved_hook_id or normalized_selector
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            filtered.append(normalized_selector)
        return filtered

    def set_hook_concat_role(self, hook_id: str, role: str):
        """Assign a hook directly to the hook concatenation plugin."""
        with self.output_processing_lock:
            return self._set_hook_concat_role_unlocked(hook_id, role)

    def _set_hook_concat_role_unlocked(self, hook_id: str, role: str):
        plugin_filename = self.get_plugin_filename_by_name('Hook Concatenation')
        if not plugin_filename or plugin_filename not in self.plugins:
            self.notify_user("Hook Concatenation plugin is not available.", level='warning')
            return

        selector_value = self.get_hook_concat_selector_value(hook_id)
        if not selector_value:
            self.notify_user("No usable selector found for this hook.", level='warning')
            return

        plugin = self.plugins[plugin_filename]
        if plugin_filename not in self.active_plugins:
            self.activate_plugin(plugin_filename)

        current_dialogue = str(plugin._state.get('dialogue_hook_id', '')).strip()
        current_prefixes = [part.strip() for part in str(plugin._state.get('prefix_hook_ids', '')).split(',') if part.strip()]

        if role == 'dialogue':
            updated_prefixes = self.filter_hook_concat_selectors(current_prefixes, hook_id)
            if not plugin.set_setting('dialogue_hook_id', selector_value):
                self.notify_user("Failed to set dialogue hook.", level='warning')
                return
            if not plugin.set_setting('prefix_hook_ids', ','.join(updated_prefixes)):
                self.notify_user("Failed to update prefix hooks.", level='warning')
                return
            role_label = 'dialogue hook'
        elif role == 'prefix':
            if self.resolve_hook_concat_selector(current_dialogue) == str(hook_id):
                self.notify_user("That hook is already assigned as the dialogue hook.", level='warning')
                return
            if not plugin.set_setting('prefix_hook_ids', selector_value):
                self.notify_user("Failed to set prefix hook.", level='warning')
                return
            role_label = 'prefix hook'
        else:
            return

        if not plugin.set_setting('enabled_mode', True):
            self.notify_user("Failed to enable hook concatenation mode.", level='warning')
            return

        if plugin_filename not in self.plugin_settings:
            self.plugin_settings[plugin_filename] = {}
        self.plugin_settings[plugin_filename]['dialogue_hook_id'] = str(plugin._state.get('dialogue_hook_id', '')).strip()
        self.plugin_settings[plugin_filename]['prefix_hook_ids'] = str(plugin._state.get('prefix_hook_ids', '')).strip()
        self.plugin_settings[plugin_filename]['enabled_mode'] = bool(plugin._state.get('enabled_mode', False))
        self.save_plugins_config()
        self.update_hook_status_panel(f"set concat {role_label}")
        self.notify_user(f"Set {selector_value} as {role_label}.", level='success')
    
    def update_event_text_layout(self):
        """Resize the session events area to its content up to a small cap."""
        if not hasattr(self, 'event_text'):
            return
        try:
            line_count = int(self.event_text.index('end-1c').split('.')[0])
        except Exception:
            line_count = 1

        visible_lines = max(1, min(4, line_count))
        self.event_text.config(height=visible_lines)
        self.event_text_default_height = visible_lines

        needs_scrollbar = line_count > 4
        if hasattr(self, 'event_scrollbar'):
            if needs_scrollbar:
                self.event_scrollbar.grid()
            else:
                self.event_scrollbar.grid_remove()

        if hasattr(self, 'update_scrollbar_visibility'):
            self.root.after(25, self.update_scrollbar_visibility)

    def append_event(self, text):
        """Append non-dialogue status text to the session event log."""
        if not hasattr(self, 'event_text'):
            return

        def do_append():
            self.event_text.config(state='normal')
            self.event_text.insert(tk.END, text)
            self.event_text.see(tk.END)
            self.event_text.config(state='disabled')
            self.update_event_text_layout()

        self.run_on_ui_thread(do_append)

    def append_output(self, text, process_plugins=True, allow_auto_copy=False):
        """Append text to the output area with plugin filtering"""
        if process_plugins:
            self.log_pipeline('append_output.received', incoming=text, allow_auto_copy=allow_auto_copy)
            self.submit_output_processing(text, allow_auto_copy)
            return
        else:
            processed_text = text
            clipboard_text = text
        self.run_on_ui_thread(self._append_output_ui, processed_text, clipboard_text, allow_auto_copy)
    
    def auto_copy_text(self, text):
        """Automatically copy new text to clipboard"""
        try:
            # Only copy non-empty, non-console text
            text_clean = text.strip()
            if text_clean and not text_clean.startswith('[Console]'):
                self.log_pipeline('clipboard.copy', text=text_clean)
                self.root.clipboard_clear()
                self.root.clipboard_append(text_clean)
                self.root.update()
            else:
                self.log_pipeline('clipboard.skip', text=text_clean)
        except Exception as exc:
            self.log_pipeline('clipboard.error', text=text, error=f'{type(exc).__name__}: {exc}')
            import traceback
            traceback.print_exc()
    
    def copy_to_clipboard(self):
        """Copy all extracted text to clipboard"""
        try:
            text_content = self.output_text.get(1.0, tk.END).strip()
            if not text_content:
                self.notify_user("No text to copy.", level='info')
                return
            
            self.root.clipboard_clear()
            self.root.clipboard_append(text_content)
            self.root.update()
            
            # Show temporary success message
            original_text = self.status_label.cget("text")
            original_color = self.status_label.cget("foreground")
            self.status_label.config(text="✓ Copied to clipboard!", 
                                    foreground=self.colors['success'])
            self.root.after(2000, lambda: self.status_label.config(
                text=original_text, foreground=original_color))
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy to clipboard:\n{str(e)}")
    
    def save_to_file(self):
        """Save extracted text to a file"""
        from tkinter import filedialog
        try:
            text_content = self.output_text.get(1.0, tk.END).strip()
            if not text_content:
                self.notify_user("No text to save.", level='info')
                return
            
            filename = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                title="Save Extracted Text"
            )
            
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(text_content)
                
                self.notify_user(f"Text saved to {filename}.", level='success', timeout_ms=6000)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save file:\n{str(e)}")
    
    def clear_output(self):
        """Clear the output and event text areas"""
        self.output_text.config(state='normal')
        self.output_text.delete(1.0, tk.END)
        self.output_text.config(state='disabled')
        if hasattr(self, 'event_text'):
            self.event_text.config(state='normal')
            self.event_text.delete(1.0, tk.END)
            self.event_text.config(state='disabled')
            self.update_event_text_layout()
        # Reset all plugins state
        self.reset_all_plugins()
        # Reset statistics
        self.stats = {'lines': 0, 'words': 0, 'chars': 0, 'start_time': None, 'last_update': time.time()}
    
    def detach_process(self):
        """Detach from the current process"""
        if self.cli_process:
            try:
                self.is_reading = False
                if self.attached_pid:
                    self.cli_process.stdin.write(f"detach -P{self.attached_pid}\n")
                    self.cli_process.stdin.flush()
                
                self.cli_process.terminate()
                self.cli_process.wait(timeout=2)
            except:
                self.cli_process.kill()
            
            self.cli_process = None
        
        self.attached_pid = None
        self.selected_hook_id = None
        with self.hooks_lock:
            self.hooks.clear()
        self.hook_tree.delete(*self.hook_tree.get_children())
        
        # Reset all plugins state
        self.reset_all_plugins()
        
        self.status_label.config(text="● Detached", foreground=self.colors['text_dim'])
        self.detach_btn.config(state='disabled')
        self.update_hook_action_state()
        self.update_hook_status_panel("detached from process")
        self.notify_user("Detached from process.", level='info')
        self.toggle_section('process', False)
        self.toggle_section('hook', False)
        
        self.append_event("\n✓ Detached from process\n")
    
    
    def create_status_bar(self):
        """Create status bar with statistics and transient notices."""
        status_frame = ttk.Frame(self.root, style="Card.TFrame", padding=(10, 5))
        status_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=15, pady=(5, 10))
        
        self.status_conn_label = ttk.Label(status_frame, text="● Disconnected", 
                                           style="Status.TLabel",
                                           foreground=self.colors['text_dim'])
        self.status_conn_label.pack(side=tk.LEFT, padx=(0, 20))
        
        self.status_lines_label = ttk.Label(status_frame, text="Lines: 0", style="Status.TLabel")
        self.status_lines_label.pack(side=tk.LEFT, padx=(0, 15))
        
        self.status_words_label = ttk.Label(status_frame, text="Words: 0", style="Status.TLabel")
        self.status_words_label.pack(side=tk.LEFT, padx=(0, 15))
        
        self.status_chars_label = ttk.Label(status_frame, text="Characters: 0", style="Status.TLabel")
        self.status_chars_label.pack(side=tk.LEFT, padx=(0, 15))
        
        self.status_rate_label = ttk.Label(status_frame, text="Rate: 0 c/s", style="Status.TLabel")
        self.status_rate_label.pack(side=tk.LEFT)

        if TRAY_AVAILABLE:
            ttk.Button(
                status_frame,
                text="🔽 Minimize to Tray",
                command=self.hide_to_tray,
                style="Secondary.TButton"
            ).pack(side=tk.RIGHT)

        self.status_notice_label = ttk.Label(
            status_frame,
            text="Ready",
            style="Status.TLabel",
            foreground=self.colors['text_dim']
        )
        self.status_notice_label.pack(side=tk.RIGHT, padx=(15, 10))

    def update_status_bar(self):
        """Update status bar with current statistics"""
        if self.attached_pid:
            conn_text = f"● Connected (PID: {self.attached_pid})"
            self.status_conn_label.config(text=conn_text, foreground=self.colors['success'])
        else:
            self.status_conn_label.config(text="● Disconnected", foreground=self.colors['text_dim'])

        self.update_hook_action_state()
        self.update_hook_status_panel()
        
        self.status_lines_label.config(text=f"Lines: {self.stats['lines']}")
        self.status_words_label.config(text=f"Words: {self.stats['words']}")
        self.status_chars_label.config(text=f"Characters: {self.stats['chars']}")
        
        if self.stats['start_time']:
            elapsed = time.time() - self.stats['start_time']
            if elapsed > 0:
                rate = self.stats['chars'] / elapsed
                self.status_rate_label.config(text=f"Rate: {rate:.1f} c/s")
        
        self.root.after(1000, self.update_status_bar)
    
    def update_statistics(self, text):
        """Update statistics when new text is added"""
        if not self.stats['start_time']:
            self.stats['start_time'] = time.time()
        
        lines = text.count('\n')
        words = len(text.split())
        chars = len(text)
        
        self.stats['lines'] += lines
        self.stats['words'] += words
        self.stats['chars'] += chars
    
    def setup_system_tray(self):
        """Setup system tray icon"""
        if not TRAY_AVAILABLE:
            return
        
        try:
            def create_tray_icon():
                # Try to use logo.webp first, fallback to generated icon
                try:
                    if self.logo_path.exists():
                        # Load the logo
                        logo_img = Image.open(self.logo_path)
                        # Resize to appropriate tray icon size (64x64)
                        logo_img = logo_img.resize((64, 64), Image.Resampling.LANCZOS)
                        # Ensure it has an alpha channel
                        if logo_img.mode != 'RGBA':
                            logo_img = logo_img.convert('RGBA')
                        return logo_img
                    else:
                        raise FileNotFoundError("Logo not found")
                except Exception:
                    # Fallback: Create a simple but visible icon
                    try:
                        image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
                        draw = ImageDraw.Draw(image)
                        
                        # Draw a solid rounded rectangle background
                        draw.rounded_rectangle([(4, 4), (60, 60)], radius=12, fill='#89b4fa')
                        
                        # Draw "T" letter in white - use simple drawing without font
                        # Draw a large "T" using rectangles for better visibility
                        # Vertical bar of T
                        draw.rectangle([(26, 16), (38, 48)], fill='white')
                        # Horizontal bar of T
                        draw.rectangle([(18, 16), (46, 26)], fill='white')
                        
                        return image
                    except Exception:
                        # Ultimate fallback - simple colored square
                        image = Image.new('RGBA', (64, 64), '#89b4fa')
                        return image
            
            def get_connection_status():
                """Get current connection status for menu"""
                if self.attached_pid:
                    return f"Connected (PID: {self.attached_pid})"
                return "Not Connected"
            
            def refresh_processes_from_tray(icon, item):
                """Refresh process list from system tray"""
                self.run_on_ui_thread(self.refresh_processes)
            
            def clear_output_from_tray(icon, item):
                """Clear output from system tray"""
                self.run_on_ui_thread(self.clear_output)
            
            def copy_to_clipboard_from_tray(icon, item):
                """Copy text to clipboard from system tray"""
                self.run_on_ui_thread(self.copy_to_clipboard)
            
            # Create enhanced menu with more options
            menu = pystray.Menu(
                item('Show Window', self.show_window, default=True),
                item('Hide to Tray', self.hide_to_tray),
                pystray.Menu.SEPARATOR,
                item(lambda text: get_connection_status(), None, enabled=False),
                pystray.Menu.SEPARATOR,
                item('Copy Text to Clipboard', copy_to_clipboard_from_tray),
                item('Clear Output', clear_output_from_tray),
                pystray.Menu.SEPARATOR,
                item('Refresh Processes', refresh_processes_from_tray),
                pystray.Menu.SEPARATOR,
                item('Exit', self.quit_app)
            )
            
            self.tray_icon = pystray.Icon(
                "sugoihook", 
                create_tray_icon(), 
                "Sugoi Hook - Text Extraction Tool",
                menu
            )
            
            # Set up single-click to show window
            def on_click(icon, button, time):
                """Handle tray icon clicks"""
                if button == pystray.MouseButton.Left:
                    # Left click shows the window
                    self.show_window()
            
            self.tray_icon.on_click = on_click
            
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
            self.root.protocol("WM_DELETE_WINDOW", self.on_window_close)
        except Exception:
            self.tray_icon = None
            self.root.protocol("WM_DELETE_WINDOW", self.quit_app)
    
    def show_window(self, icon=None, item=None):
        """Show the main window"""
        if threading.current_thread() is not threading.main_thread():
            self.run_on_ui_thread(self.show_window)
            return
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.is_minimized_to_tray = False
        
        # Update tray icon tooltip with current status
        if TRAY_AVAILABLE and self.tray_icon:
            if self.attached_pid:
                self.tray_icon.title = f"Sugoi Hook - Connected (PID: {self.attached_pid})"
            else:
                self.tray_icon.title = "Sugoi Hook - Text Extraction Tool"
    
    def hide_to_tray(self, icon=None, item=None):
        """Hide window to system tray"""
        if threading.current_thread() is not threading.main_thread():
            self.run_on_ui_thread(self.hide_to_tray)
            return
        if TRAY_AVAILABLE:
            self.root.withdraw()
            self.is_minimized_to_tray = True
    
    def on_window_close(self):
        """Handle window close button"""
        # Save configuration on close
        self.persist_window_geometry()
        self.save_plugins_config()
        
        if TRAY_AVAILABLE:
            self.hide_to_tray()
        else:
            self.quit_app()
    
    def quit_app(self, icon=None, item=None):
        """Completely quit the application"""
        if threading.current_thread() is not threading.main_thread():
            self.run_on_ui_thread(self.quit_app)
            return
        if self.shutdown_started:
            return
        self.shutdown_started = True
        # Save configuration on exit
        self.save_plugins_config()
        self.output_pipeline.stop()
        with self.output_processing_lock:
            self.shutdown_plugin_instances()
        
        if self.cli_process:
            self.detach_process()
        if TRAY_AVAILABLE and self.tray_icon:
            self.tray_icon.stop()
        with self.ui_callback_lock:
            self.ui_callback_shutdown = True
            self.ui_callback_queue.clear()
        self.root.quit()
        self.root.destroy()
    
    def toggle_fullscreen(self, event=None):
        """Toggle fullscreen mode"""
        self.is_fullscreen = not self.is_fullscreen
        self.root.attributes('-fullscreen', self.is_fullscreen)
        self.adjust_layout_for_fullscreen()
        return "break"
    
    def exit_fullscreen(self, event=None):
        """Exit fullscreen mode"""
        if self.is_fullscreen:
            self.is_fullscreen = False
            self.root.attributes('-fullscreen', False)
            self.adjust_layout_for_fullscreen()
        return "break"
    
    def on_window_configure(self, event=None):
        """Handle window configuration changes"""
        # Detect if window is maximized (not fullscreen)
        if event and event.widget == self.root:
            # Check if window state changed
            self.root.after(100, self.adjust_layout_for_fullscreen)
            self.schedule_window_geometry_save()
    
    def adjust_layout_for_fullscreen(self):
        """Adjust component heights based on fullscreen/windowed mode."""
        if self.is_fullscreen:
            self.process_tree.config(height=4)
            self.hook_tree.config(height=5)
            self.plugins_tree.config(height=9)
            self.event_text.config(height=max(self.event_text_default_height, 4))
            self.output_text.config(height=13)
        else:
            self.process_tree.config(height=self.process_tree_default_height)
            self.hook_tree.config(height=self.hook_tree_default_height)
            self.plugins_tree.config(height=7)
            self.event_text.config(height=self.event_text_default_height)
            self.output_text.config(height=self.output_text_default_height)
    
    def on_closing(self):
        """Handle window closing"""
        # Save configuration on close
        self.quit_app()

def main():
    log_path = setup_runtime_logging()
    logging.info('Entered main%s', f' (log: {log_path})' if log_path else '')
    logging.info('Verbose runtime debug logging: %s', 'enabled' if runtime_debug_logging_enabled() else 'disabled')

    # Source and packaged launches now stay in the current user context.
    launcher_path = get_runtime_launcher_path()
    is_frozen = getattr(sys, 'frozen', False)
    is_nuitka = bool(getattr(sys, '__compiled__', False) or (
        launcher_path.suffix.lower() == '.exe' and
        launcher_path.resolve() != Path(__file__).resolve()
    ))
    launched_script_path = Path(sys.argv[0]).suffix.lower() if sys.argv else ''
    is_script_launch = launched_script_path == '.py'
    is_compiled = is_frozen or is_nuitka or not is_script_launch
    logging.info(
        'Startup flags: is_frozen=%s is_nuitka=%s is_compiled=%s is_script_launch=%s executable=%s argv0=%s',
        is_frozen,
        is_nuitka,
        is_compiled,
        is_script_launch,
        sys.executable,
        sys.argv[0] if sys.argv else '',
    )
    if runtime_debug_logging_enabled():
        logging.info(
            'Runtime paths: bundle_base=%s user_data_dir=%s launcher=%s default_engine=%s debug_enabled=%s',
            get_runtime_bundle_base_path(),
            get_runtime_user_data_path(),
            launcher_path,
            'luna',
            True,
        )
    logging.info('Auto-elevation is disabled; continuing in the current user context.')

    # Enable DPI awareness for crisp text
    try:
        logging.info('Setting process DPI awareness.')
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        logging.info('DPI awareness set.')
    except Exception:
        logging.exception('Failed to set DPI awareness.')

    logging.info('Creating Tk root window.')
    root = tk.Tk()
    logging.info('Tk root window created.')

    def report_callback_exception(exc_type, exc_value, exc_traceback):
        logging.critical(
            'Tkinter callback exception',
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    root.report_callback_exception = report_callback_exception

    logging.info('Constructing SugoiHookGUI.')
    app = SugoiHookGUI(root)
    logging.info('SugoiHookGUI constructed.')
    if runtime_debug_logging_enabled():
        logging.info(
            'App summary: active_engine=%s bundled_plugins_folder=%s user_plugins_folder=%s plugins_config_path=%s game_profiles_path=%s',
            app.current_engine,
            getattr(app, 'bundled_plugins_folder', None),
            getattr(app, 'plugins_folder', None),
            getattr(app, 'plugins_config_path', None),
            getattr(app, 'game_profiles_path', None),
        )
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    logging.info('Entering Tk mainloop%s', f' (log: {log_path})' if log_path else '')
    root.mainloop()
    logging.info('Tk mainloop exited.')

if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.critical('Fatal startup exception', exc_info=True)
        raise








