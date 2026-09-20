"""Characterization coverage for GUI extraction boundaries.

These tests intentionally exercise the current facade.  They make existing
runtime decisions and cross-thread behavior explicit before those concerns
move into dedicated modules.
"""

from collections import deque
from hashlib import md5
from io import StringIO
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import SugoiHook_gui as gui
from luna_session import LunaProcessSession


gui.sys.stdout = gui.ORIGINAL_STDOUT
gui.sys.stderr = gui.ORIGINAL_STDERR


class RecordingRoot:
    def __init__(self):
        self.after_calls = []

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))


class RuntimePathCharacterizationTests(unittest.TestCase):
    def test_source_runtime_uses_the_gui_module_directory(self):
        expected = Path(gui.__file__).resolve().parent
        with patch.object(gui.sys, "frozen", False, create=True), \
                patch.object(gui.sys, "__compiled__", False, create=True), \
                patch.object(gui.sys, "executable", r"C:\\Python311\\python.exe"), \
                patch.object(gui.sys, "argv", [str(Path(gui.__file__).resolve())]):
            self.assertEqual(gui.get_runtime_launcher_path(), Path(gui.__file__).resolve())
            self.assertEqual(gui.get_runtime_bundle_base_path(), expected)
            self.assertEqual(gui.get_runtime_user_data_path(), expected)

    def test_compiled_runtime_uses_the_executable_directory_for_bundle_and_data(self):
        executable = Path(r"C:\\Release\\SugoiHook.exe")
        with patch.object(gui.sys, "frozen", False, create=True), \
                patch.object(gui.sys, "__compiled__", True, create=True), \
                patch.object(gui.sys, "executable", str(executable)), \
                patch.object(gui.sys, "argv", [str(executable)]):
            self.assertEqual(gui.get_runtime_launcher_path(), executable)
            self.assertEqual(gui.get_runtime_bundle_base_path(), executable.parent)
            self.assertEqual(gui.get_runtime_user_data_path(), executable.parent)

    def test_frozen_runtime_uses_the_executable_directory_for_runtime_helpers(self):
        executable = Path(r"C:\\Temp\\onefile\\SugoiHook.exe")
        with patch.object(gui.sys, "frozen", True, create=True), \
                patch.object(gui.sys, "__compiled__", False, create=True), \
                patch.object(gui.sys, "executable", str(executable)), \
                patch.object(gui.sys, "argv", [str(executable)]):
            self.assertEqual(gui.get_runtime_launcher_path(), executable)
            self.assertEqual(gui.get_runtime_bundle_base_path(), executable.parent)
            self.assertEqual(gui.get_runtime_user_data_path(), executable.parent)


class UIQueueCharacterizationTests(unittest.TestCase):
    def make_app(self):
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        app.ui_callback_lock = threading.Lock()
        app.ui_callback_queue = deque()
        app.ui_callback_shutdown = False
        app.root = RecordingRoot()
        return app

    def test_background_callbacks_are_fifo_and_callback_failures_do_not_stop_later_work(self):
        app = self.make_app()
        delivered = []

        def enqueue():
            app.run_on_ui_thread(delivered.append, "first")
            app.run_on_ui_thread(lambda: (_ for _ in ()).throw(RuntimeError("expected callback failure")))
            app.run_on_ui_thread(delivered.append, "last")

        worker = threading.Thread(target=enqueue)
        worker.start()
        worker.join()

        with self.assertLogs(level="ERROR") as logs:
            app.drain_ui_callbacks()

        self.assertEqual(delivered, ["first", "last"])
        self.assertEqual(list(app.ui_callback_queue), [])
        self.assertEqual([delay for delay, _ in app.root.after_calls], [10])
        self.assertTrue(any("UI callback failed" in message for message in logs.output))

    def test_main_thread_callbacks_run_immediately_and_shutdown_rejects_background_work(self):
        app = self.make_app()
        delivered = []
        app.run_on_ui_thread(delivered.append, "immediate")

        with app.ui_callback_lock:
            app.ui_callback_shutdown = True

        worker = threading.Thread(target=app.run_on_ui_thread, args=(delivered.append, "rejected"))
        worker.start()
        worker.join()

        self.assertEqual(delivered, ["immediate"])
        self.assertEqual(list(app.ui_callback_queue), [])


class ProcessAndProfileCharacterizationTests(unittest.TestCase):
    def test_process_exclusion_rules_cover_exact_name_path_and_patterns(self):
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        app.excluded_executables = {"explorer.exe"}
        app.system_dirs = [r"c:\\windows\\system32"]
        app.system_process_patterns = ["svchost"]
        app.bloatware_patterns = ["discord"]

        self.assertTrue(app.should_exclude_process("Explorer.exe"))
        self.assertTrue(app.should_exclude_process("game.exe", r"C:\\Windows\\System32\\game.exe"))
        self.assertTrue(app.should_exclude_process("svchost-helper.exe"))
        self.assertTrue(app.should_exclude_process("DiscordGame.exe"))
        self.assertFalse(app.should_exclude_process("visual-novel.exe", r"D:\\Games\\visual-novel.exe"))

    def test_game_identity_hashes_executable_path_and_size(self):
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "game.exe"
            executable.write_bytes(b"test executable")

            class Process:
                def exe(self):
                    return str(executable)

            with patch.object(gui.psutil, "Process", return_value=Process()):
                game_id, exe_path, exe_size = app.generate_game_id(1234)

            self.assertEqual(exe_path, str(executable))
            self.assertEqual(exe_size, len(b"test executable"))
            self.assertEqual(game_id, md5(f"{executable}_{exe_size}".encode()).hexdigest())


class LunaOutputCharacterizationTests(unittest.TestCase):
    def test_console_new_hook_and_hook_text_lines_preserve_current_routing(self):
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        process = type("Process", (), {
            "stdout": StringIO(
                "[Console] attached\n"
                "[#7|game.exe:EXBWX0@25C880:thread] first line\n"
                "[#7|game.exe:EXBWX0@25C880:thread] second line\n"
            ),
        })()
        session = LunaProcessSession(process, 1, 1234, "game.exe")
        app.luna_session_lock = threading.RLock()
        app.luna_session = session
        app.output_processing_lock = threading.RLock()
        app.hooks_lock = threading.Lock()
        app.hooks = {}
        app.hook_event_sequence = 0
        app.appended_output = []
        app.routed_events = []
        app.ui_events = []
        app.append_output = lambda text, translate, auto_copy: app.appended_output.append((text, translate, auto_copy))
        app.route_hook_output = lambda hook_id, text, sequence: app.routed_events.append((hook_id, text, sequence))
        app.run_on_ui_thread = lambda callback, *args: callback(*args)
        app.add_hook_to_list = lambda hook_id, name: app.ui_events.append(("new", hook_id, name))
        app.update_hook_preview = lambda hook_id, text: app.ui_events.append(("preview", hook_id, text))

        app.read_luna_output(session)

        self.assertEqual(app.appended_output, [("[Console] attached\n", True, False)])
        self.assertEqual(app.routed_events, [("7", "first line", 1), ("7", "second line", 2)])
        self.assertEqual(app.ui_events, [
            ("new", "7", "EXBWX0@25C880"),
            ("preview", "7", "first line"),
            ("preview", "7", "second line"),
        ])
        self.assertEqual(app.hooks["7"]["texts"], ["first line", "second line"])
        self.assertEqual(app.hooks["7"]["latest_event_sequence"], 2)


class PluginDiscoveryCharacterizationTests(unittest.TestCase):
    def test_failed_active_plugin_restore_is_logged_but_plugin_remains_discovered(self):
        source = """
from plugins import HookPlugin

class FailingPlugin(HookPlugin):
    def process_text(self, text):
        return text

    def on_enable(self):
        raise RuntimeError("startup activation failed")

plugin = FailingPlugin()
"""
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        app.plugins = {}
        app.plugin_file_paths = {}
        app.plugin_module_names = {}
        app.plugin_settings = {}
        app.active_plugins = ["failing.py"]
        app.plugin_order = []

        with tempfile.TemporaryDirectory() as directory:
            plugin_path = Path(directory) / "failing.py"
            plugin_path.write_text(source, encoding="utf-8")
            app.bundled_plugins_folder = None
            app.plugins_folder = Path(directory)
            saved = []
            app.save_plugins_config = lambda: saved.append(True) or True

            with self.assertLogs(level="ERROR") as logs:
                app.discover_plugins()

        self.assertIn("failing.py", app.plugins)
        self.assertEqual(app.active_plugins, ["failing.py"])
        self.assertTrue(app.plugins["failing.py"].enabled)
        self.assertEqual(app.plugin_order, ["failing.py"])
        self.assertEqual(saved, [True])
        self.assertTrue(any("Failed to discover plugin" in message for message in logs.output))
        app.shutdown_plugin_instances()


if __name__ == "__main__":
    unittest.main()
