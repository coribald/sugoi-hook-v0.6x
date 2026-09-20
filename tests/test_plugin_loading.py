import importlib
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import SugoiHook_gui as gui


gui.sys.stdout = gui.ORIGINAL_STDOUT
gui.sys.stderr = gui.ORIGINAL_STDERR


PLUGIN_SOURCE = """
from plugins import HookPlugin

class TestPlugin(HookPlugin):
    name = {name!r}

    def __init__(self):
        super().__init__()
        self.disabled_by_reload = False

    def process_text(self, text):
        return text

    def on_disable(self):
        self.disabled_by_reload = True

plugin = TestPlugin()
"""


class PluginLoadingTests(unittest.TestCase):
    def make_app(self):
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        app.plugins = {}
        app.plugin_file_paths = {}
        app.plugin_module_names = {}
        app.active_plugins = []
        app.base_path = Path(gui.__file__).resolve().parent
        return app

    def test_deep_translator_imports_vendored_package_not_its_plugin_module(self):
        app = self.make_app()
        plugin_path = app.base_path / "plugins" / "deep_translator.py"
        previous_package = sys.modules.pop("deep_translator", None)
        try:
            plugin = app.load_plugin(plugin_path)
            self.assertIsNotNone(plugin)
            plugin.on_enable()

            package_module = sys.modules["deep_translator"]
            self.assertNotEqual(Path(package_module.__file__).resolve(), plugin_path.resolve())
            self.assertTrue(str(Path(package_module.__file__).resolve()).startswith(str(app.base_path / "deep_translator")))
        finally:
            app.shutdown_plugin_instances()
            for module_name in list(sys.modules):
                module = sys.modules.get(module_name)
                module_file = getattr(module, "__file__", None)
                if module_name == "deep_translator" or (
                    module_name.startswith("deep_translator.")
                    and module_file
                    and str(Path(module_file).resolve()).startswith(str(app.base_path / "deep_translator"))
                ):
                    sys.modules.pop(module_name, None)
            if previous_package is not None:
                sys.modules["deep_translator"] = previous_package

    def test_invalid_module_plugin_is_rejected_without_leaking_module(self):
        app = self.make_app()
        with tempfile.TemporaryDirectory() as directory:
            plugin_path = Path(directory) / "invalid.py"
            plugin_path.write_text("plugin = object()\n", encoding="utf-8")
            module_name = app.get_plugin_module_name(plugin_path)

            self.assertIsNone(app.load_plugin(plugin_path))
            self.assertNotIn(module_name, sys.modules)
            self.assertNotIn(plugin_path.name, app.plugins)

    def test_replacing_same_filename_disables_old_instance_and_replaces_module(self):
        app = self.make_app()
        with tempfile.TemporaryDirectory() as directory:
            plugin_path = Path(directory) / "example.py"
            plugin_path.write_text(textwrap.dedent(PLUGIN_SOURCE.format(name="first")), encoding="utf-8")
            first_plugin = app.load_plugin(plugin_path)
            first_module_name = app.plugin_module_names[plugin_path.name]

            plugin_path.write_text(textwrap.dedent(PLUGIN_SOURCE.format(name="second-version")), encoding="utf-8")
            importlib.invalidate_caches()
            second_plugin = app.load_plugin(plugin_path)

            self.assertTrue(first_plugin.disabled_by_reload)
            self.assertIsNot(first_plugin, second_plugin)
            self.assertEqual(second_plugin.name, "second-version")
            self.assertEqual(app.plugin_module_names[plugin_path.name], first_module_name)
            self.assertIn(first_module_name, sys.modules)

    def test_unload_removes_only_tracked_dynamic_module(self):
        app = self.make_app()
        standard_json_module = json
        with tempfile.TemporaryDirectory() as directory:
            plugin_path = Path(directory) / "json.py"
            plugin_path.write_text(textwrap.dedent(PLUGIN_SOURCE.format(name="json plugin")), encoding="utf-8")
            app.load_plugin(plugin_path)
            dynamic_module_name = app.plugin_module_names[plugin_path.name]

            app.shutdown_plugin_instances()

            self.assertIs(sys.modules["json"], standard_json_module)
            self.assertNotIn(dynamic_module_name, sys.modules)


if __name__ == "__main__":
    unittest.main()
