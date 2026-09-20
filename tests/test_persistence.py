import json
import tempfile
import threading
import unittest
from pathlib import Path

import SugoiHook_gui as gui
from json_persistence import JsonPersistenceError, backup_path_for, load_json_object, save_json_object_atomic


class PersistenceRegressionTests(unittest.TestCase):
    def test_atomic_save_keeps_last_valid_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            save_json_object_atomic(path, {"version": 1})
            save_json_object_atomic(path, {"version": 2})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"version": 2})
            self.assertEqual(json.loads(backup_path_for(path).read_text(encoding="utf-8")), {"version": 1})

    def test_malformed_primary_recovers_last_valid_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            save_json_object_atomic(path, {"version": 1})
            save_json_object_atomic(path, {"version": 2})
            path.write_text("{broken", encoding="utf-8")

            loaded, recovered = load_json_object(path)

            self.assertTrue(recovered)
            self.assertEqual(loaded, {"version": 1})

    def test_failed_write_leaves_previous_config_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            save_json_object_atomic(path, {"version": 1})

            with self.assertRaises(JsonPersistenceError):
                save_json_object_atomic(path, {"not_serializable": object()})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"version": 1})

    def test_malformed_config_without_backup_fails_predictably(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("[]", encoding="utf-8")

            with self.assertRaisesRegex(JsonPersistenceError, "top-level JSON value must be an object"):
                load_json_object(path)

    def test_plugin_config_rejects_invalid_shape_without_overwriting_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plugins_config.json"
            invalid_config = {"active_plugins": "not-a-list"}
            path.write_text(json.dumps(invalid_config), encoding="utf-8")
            app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
            app.plugins_config_path = path
            app.active_plugins = ["existing.py"]
            app.plugin_order = ["existing.py"]
            app.plugin_settings = {"existing.py": {"enabled": True}}
            app.window_geometry = None
            app.compact_window_geometry = None
            app.config_warnings = []

            app.load_plugins_config()

            self.assertEqual(app.active_plugins, [])
            self.assertEqual(app.plugin_order, [])
            self.assertEqual(app.plugin_settings, {})
            self.assertEqual(len(app.config_warnings), 1)

    def test_rejected_plugin_setting_is_removed_from_persisted_settings(self):
        class SelectivePlugin:
            def set_setting(self, name, value):
                return name == "accepted"

        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        app.output_processing_lock = threading.RLock()
        app.plugin_settings = {"plugin.py": {"accepted": "old", "rejected": "old"}}

        accepted = app.apply_plugin_settings(
            "plugin.py", SelectivePlugin(), {"accepted": "new", "rejected": "bad"}
        )

        self.assertEqual(accepted, {"accepted": "new"})
        self.assertEqual(app.plugin_settings, {"plugin.py": {"accepted": "new"}})


if __name__ == "__main__":
    unittest.main()
