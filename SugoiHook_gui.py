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
import types
import copy
from pathlib import Path

from json_persistence import JsonPersistenceError, load_json_object, save_json_object_atomic
from luna_session import LunaProcessSession
from luna_controller import LunaController, LunaHookTextEvent
from plugin_settings_dialog import PluginSettingsDialog
from profile_manager_dialog import ProfileManagerDialog
from hook_help_dialog import show_hook_help as show_hook_help_dialog
from main_window import MainWindowView
from output_pipeline import OutputPipeline
from plugin_manager import DYNAMIC_PLUGIN_PACKAGE, PluginManager
from plugin_pipeline import PluginPipeline
from game_profile_store import GameProfileStore
from process_service import ProcessService, windows_process_architecture
from hook_registry import HookRegistry
from runtime_context import resolve_runtime_context
from ui_dispatcher import UIThreadDispatcher

ORIGINAL_STDOUT = sys.stdout
ORIGINAL_STDERR = sys.stderr
EARLY_LOG_STREAM = None
EARLY_LOG_PATH = None
def is_valid_plugins_config(config):
    return (
        isinstance(config.get('active_plugins', []), list)
        and all(isinstance(name, str) for name in config.get('active_plugins', []))
        and isinstance(config.get('plugin_order', []), list)
        and all(isinstance(name, str) for name in config.get('plugin_order', []))
        and isinstance(config.get('plugin_settings', {}), dict)
        and all(isinstance(name, str) and isinstance(settings, dict)
                for name, settings in config.get('plugin_settings', {}).items())
        and (config.get('window_geometry') is None or isinstance(config.get('window_geometry'), str))
        and (config.get('compact_window_geometry') is None or isinstance(config.get('compact_window_geometry'), str))
    )


def is_valid_game_profiles(config):
    return all(isinstance(game_id, str) and isinstance(profile, dict) for game_id, profile in config.items())


def get_runtime_launcher_path() -> Path:
    """Compatibility delegate for legacy callers and early bootstrap."""
    return resolve_runtime_context(module_path=__file__).launcher_path


def get_runtime_bundle_base_path() -> Path:
    """Compatibility delegate for legacy callers and early bootstrap."""
    return resolve_runtime_context(module_path=__file__).runtime_bundle_base_path


def get_runtime_user_data_path() -> Path:
    """Compatibility delegate for legacy callers and early bootstrap."""
    return resolve_runtime_context(module_path=__file__).user_data_dir


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
from sugoihook_app import SugoiHookGUI

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








