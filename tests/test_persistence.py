import json
import tempfile
import threading
import unittest
from pathlib import Path

import SugoiHook_gui as gui
from json_persistence import JsonPersistenceError, backup_path_for, load_json_object, save_json_object_atomic
from plugins.overlay_window import OverlayWindowPlugin


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

    def test_failed_plugin_config_save_rolls_back_runtime_and_memory(self):
        class StatefulPlugin:
            def __init__(self):
                self.value = "old"

            def get_settings(self):
                return {"value": (self.value, "str", "Value")}

            def set_setting(self, name, value):
                self.value = value
                return True

        plugin = StatefulPlugin()
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        app.output_processing_lock = threading.RLock()
        app.plugin_settings = {"plugin.py": {"value": "old"}}
        app.save_plugins_config = lambda: False

        saved, accepted = app.save_plugin_settings_transactionally(
            "plugin.py", plugin, {"value": "new"}
        )

        self.assertFalse(saved)
        self.assertEqual(accepted, {"value": "new"})
        self.assertEqual(plugin.value, "old")
        self.assertEqual(app.plugin_settings, {"plugin.py": {"value": "old"}})

    def test_required_plugin_settings_roll_back_when_one_is_rejected(self):
        class SelectivePlugin:
            def __init__(self):
                self.values = {"accepted": "old", "rejected": "old"}

            def get_settings(self):
                return {
                    name: (value, "str", name)
                    for name, value in self.values.items()
                }

            def set_setting(self, name, value):
                if name == "rejected":
                    return False
                self.values[name] = value
                return True

        plugin = SelectivePlugin()
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        app.output_processing_lock = threading.RLock()
        app.plugin_settings = {"plugin.py": dict(plugin.values)}
        app.save_plugins_config = lambda: True
        notices = []
        app.notify_user = lambda message, **kwargs: notices.append(message)

        saved, _ = app.save_plugin_settings_transactionally(
            "plugin.py",
            plugin,
            {"accepted": "new", "rejected": "bad"},
            require_all=True,
        )

        self.assertFalse(saved)
        self.assertEqual(plugin.values, {"accepted": "old", "rejected": "old"})
        self.assertEqual(app.plugin_settings, {"plugin.py": {"accepted": "old", "rejected": "old"}})
        self.assertEqual(len(notices), 1)

    def test_failed_game_profile_save_restores_previous_snapshot(self):
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        original = {"old": {"exe_name": "old.exe"}}
        app.game_profiles = original
        app.save_game_profiles = lambda: False

        saved = app.commit_game_profiles({"new": {"exe_name": "new.exe"}})

        self.assertFalse(saved)
        self.assertIs(app.game_profiles, original)

    def test_failed_activation_save_disables_plugin_again(self):
        class LifecyclePlugin:
            enabled = False

            def __init__(self):
                self.enable_count = 0
                self.disable_count = 0

            def on_enable(self):
                self.enable_count += 1

            def on_disable(self):
                self.disable_count += 1

        plugin = LifecyclePlugin()
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        app.output_processing_lock = threading.RLock()
        app.plugins = {"plugin.py": plugin}
        app.active_plugins = []
        app.save_plugins_config = lambda: False

        activated = app.activate_plugin("plugin.py")

        self.assertFalse(activated)
        self.assertEqual(app.active_plugins, [])
        self.assertFalse(plugin.enabled)
        self.assertEqual((plugin.enable_count, plugin.disable_count), (1, 1))

    def test_overlay_setting_rolls_back_when_overlay_config_save_fails(self):
        plugin = OverlayWindowPlugin.__new__(OverlayWindowPlugin)
        plugin.config = {"window_opacity": 80}
        plugin.overlay = None
        plugin.enabled = False
        plugin.save_config = lambda: False

        accepted = plugin.set_setting("window_opacity", 90)

        self.assertFalse(accepted)
        self.assertEqual(plugin.config["window_opacity"], 80)


if __name__ == "__main__":
    unittest.main()
