"""Plugin lifecycle, dynamic-module ownership, and configuration persistence."""

import copy
import hashlib
import importlib.util
import logging
import re
import sys
import types
from pathlib import Path

from json_persistence import JsonPersistenceError, load_json_object, save_json_object_atomic


DYNAMIC_PLUGIN_PACKAGE = "sugoihook_dynamic_plugins"


class PluginManager:
    """Single mutable owner for loaded plugins and their persisted settings."""

    def __init__(self, host, *, plugin_base, config_path=None, bundled_dir=None, user_dir=None,
                 output_lock=None, config_validator=None, issue_reporter=None, debug_enabled=None):
        self.host = host
        self.plugin_base = plugin_base
        self.config_path = config_path
        self.bundled_dir = bundled_dir
        self.user_dir = user_dir
        self.output_lock = output_lock
        self.config_validator = config_validator
        self.issue_reporter = issue_reporter or (lambda path, error: None)
        self.debug_enabled = debug_enabled or (lambda: False)
        self.plugins = {}
        self.active_plugins = []
        self.plugin_order = []
        self.plugin_settings = {}
        self.plugin_file_paths = {}
        self.plugin_module_names = {}

    def _locked(self):
        return self.output_lock

    def init(self):
        if self.user_dir:
            Path(self.user_dir).mkdir(parents=True, exist_ok=True)
        self.load_config()
        self.discover()

    def load_config(self):
        self.active_plugins, self.plugin_order, self.plugin_settings = [], [], {}
        if not self.config_path:
            return
        try:
            config, recovered = load_json_object(self.config_path, self.config_validator)
        except JsonPersistenceError as error:
            self.issue_reporter(self.config_path, error)
            return
        if config is None:
            return
        if recovered:
            self.issue_reporter(self.config_path, "the primary file was invalid; recovered the last valid saved settings")
        self.active_plugins = config.get("active_plugins", [])
        self.plugin_order = config.get("plugin_order", [])
        self.plugin_settings = config.get("plugin_settings", {})
        self.host.window_geometry = config.get("window_geometry")
        self.host.compact_window_geometry = config.get("compact_window_geometry")

    def save_config(self):
        if not self.config_path:
            return False
        if not self.plugin_order:
            self.plugin_order = sorted(self.plugins)
        config = {"active_plugins": self.active_plugins, "plugin_order": self.plugin_order,
                  "plugin_settings": self.plugin_settings,
                  "window_geometry": getattr(self.host, "window_geometry", None),
                  "compact_window_geometry": getattr(self.host, "compact_window_geometry", None)}
        try:
            save_json_object_atomic(self.config_path, config, self.config_validator)
            return True
        except JsonPersistenceError as error:
            self.issue_reporter(self.config_path, error)
            return False

    def discover(self):
        paths = []
        for path in (self.bundled_dir, self.user_dir):
            if path and Path(path).exists() and Path(path) not in paths:
                paths.append(Path(path))
        if not paths:
            return
        current = set()
        for directory in paths:
            for plugin_path in directory.glob("*.py"):
                if plugin_path.name.startswith("_"):
                    continue
                current.add(plugin_path.name)
                try:
                    plugin = self.load(plugin_path)
                    if plugin and plugin_path.name in self.plugin_settings:
                        self.apply_settings(plugin_path.name, plugin, dict(self.plugin_settings[plugin_path.name]))
                    if plugin and plugin_path.name in self.active_plugins:
                        plugin.enabled = True
                        plugin.on_enable()
                except Exception:
                    logging.exception("Failed to discover plugin: %s", plugin_path)
        for filename in list(self.plugins):
            if filename not in current:
                self.unload(filename)
        self.active_plugins = [name for name in self.active_plugins if name in self.plugins]
        self.plugin_file_paths = {name: path for name, path in self.plugin_file_paths.items() if name in current}
        self.plugin_order = [name for name in self.plugin_order if name in self.plugins]
        self.plugin_order.extend(name for name in self.plugins if name not in self.plugin_order)
        self.save_config()

    def module_name(self, plugin_path):
        resolved = str(Path(plugin_path).resolve()).casefold()
        stem = re.sub(r"\W+", "_", Path(plugin_path).stem).strip("_") or "plugin"
        return f"{DYNAMIC_PLUGIN_PACKAGE}.{stem}_{hashlib.sha256(resolved.encode()).hexdigest()[:16]}"

    def _ensure_package(self):
        if DYNAMIC_PLUGIN_PACKAGE not in sys.modules:
            package = types.ModuleType(DYNAMIC_PLUGIN_PACKAGE)
            package.__path__ = []
            sys.modules[DYNAMIC_PLUGIN_PACKAGE] = package

    def load(self, plugin_path):
        plugin_path = Path(plugin_path)
        module_name = self.module_name(plugin_path)
        try:
            self.unload(plugin_path.name)
            self._ensure_package()
            spec = importlib.util.spec_from_file_location(module_name, plugin_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not create an import specification for {plugin_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            instance = getattr(module, "plugin", None)
            if instance is None:
                for name in dir(module):
                    candidate = getattr(module, name)
                    if isinstance(candidate, type) and issubclass(candidate, self.plugin_base) and candidate is not self.plugin_base:
                        instance = candidate()
                        break
            if not isinstance(instance, self.plugin_base):
                raise TypeError(f"module.plugin must be a {self.plugin_base.__name__}, got {type(instance).__name__}")
            instance.app = self.host
            self.plugins[plugin_path.name] = instance
            self.plugin_file_paths[plugin_path.name] = plugin_path
            self.plugin_module_names[plugin_path.name] = module_name
            return instance
        except Exception:
            sys.modules.pop(module_name, None)
            logging.exception("Failed to load plugin from %s", plugin_path)
            return None

    def unload(self, filename):
        plugin = self.plugins.get(filename)
        if plugin is not None:
            try: plugin.enabled = False
            except Exception: logging.exception("Failed to mark plugin disabled during unload: %s", filename)
            try: plugin.on_disable()
            except Exception: logging.exception("Failed to disable plugin during unload: %s", filename)
        self.plugins.pop(filename, None); self.plugin_file_paths.pop(filename, None)
        module_name = self.plugin_module_names.pop(filename, None)
        if module_name: sys.modules.pop(module_name, None)

    def shutdown(self):
        for filename in list(self.plugins): self.unload(filename)
        self.active_plugins = []

    def activate(self, filename):
        with self._locked():
            if filename not in self.plugins or filename in self.active_plugins: return False
            plugin = self.plugins[filename]; self.active_plugins.append(filename)
            try: plugin.enabled = True; plugin.on_enable()
            except Exception:
                logging.exception("Failed to enable plugin: %s", filename); self.active_plugins.remove(filename)
                try: plugin.enabled = False; plugin.on_disable()
                except Exception: logging.exception("Failed to clean up plugin after enable failure: %s", filename)
                return False
            if self.save_config(): return True
            self.active_plugins.remove(filename)
            try: plugin.enabled = False; plugin.on_disable()
            except Exception: logging.exception("Failed to disable plugin after config save failure: %s", filename)
            return False

    def deactivate(self, filename):
        with self._locked():
            if filename not in self.active_plugins: return False
            index = self.active_plugins.index(filename); self.active_plugins.remove(filename); plugin = self.plugins.get(filename)
            if plugin:
                try: plugin.enabled = False; plugin.on_disable()
                except Exception:
                    logging.exception("Failed to disable plugin: %s", filename); self.active_plugins.insert(index, filename)
                    try: plugin.enabled = True; plugin.on_enable()
                    except Exception: logging.exception("Failed to restore plugin after disable failure: %s", filename)
                    return False
            if self.save_config(): return True
            self.active_plugins.insert(index, filename)
            if plugin:
                try: plugin.enabled = True; plugin.on_enable()
                except Exception: logging.exception("Failed to restore plugin after config save failure: %s", filename)
            return False

    def apply_settings(self, filename, plugin, values):
        accepted = {}
        with self._locked():
            for name, value in values.items():
                try:
                    if plugin.set_setting(name, value): accepted[name] = value
                    else: logging.warning("Plugin %s rejected setting %s", filename, name)
                except Exception: logging.exception("Plugin %s failed to apply setting %s", filename, name)
            persisted = self.plugin_settings.setdefault(filename, {})
            for name in values: persisted.pop(name, None)
            persisted.update(accepted)
            if not persisted: self.plugin_settings.pop(filename, None)
        return accepted

    def save_settings_transactionally(self, filename, plugin, values, require_all=False):
        existed = filename in self.plugin_settings; previous = copy.deepcopy(self.plugin_settings.get(filename, {}))
        runtime = {name: spec[0] for name, spec in plugin.get_settings().items() if name in values and spec}
        accepted = self.apply_settings(filename, plugin, values)
        if not (require_all and len(accepted) != len(values)) and self.save_config(): return True, accepted
        with self._locked():
            for name, old in runtime.items():
                if name in accepted:
                    try: plugin.set_setting(name, old)
                    except Exception: logging.exception("Plugin %s failed to roll back setting %s", filename, name)
            if existed: self.plugin_settings[filename] = previous
            else: self.plugin_settings.pop(filename, None)
        return False, accepted
