"""Plugin text transformation policy, separate from output-worker scheduling."""

import logging
import re


class PluginPipeline:
    def __init__(self, host, plugins_available):
        self.host = host
        self.plugins_available = plugins_available

    def run_pre_translation(self, text):
        if not self.plugins_available(): return text, text, [], []
        display = clipboard = text; translators = []; post = []; translation_started = False
        order = [name for name in self.host.plugin_order if name in self.host.active_plugins]
        self.host.log_pipeline('pre_translation.start', incoming=text, active_plugins=order)
        for name in order:
            plugin = self.host.plugins.get(name)
            if not plugin or not plugin.enabled: continue
            if getattr(plugin, 'is_translation_plugin', False):
                translation_started = True; translators.append(plugin); continue
            if translation_started:
                post.append(plugin); continue
            try:
                if display is not None: display = plugin.process_text(display)
                if clipboard is not None: clipboard = plugin.process_clipboard_text(clipboard)
            except Exception: logging.exception('Pre-translation plugin failed: %s', name)
        return display, clipboard, translators, post

    @staticmethod
    def translation_worthy(text):
        stripped = text.strip() if isinstance(text, str) else text
        return bool(stripped) and not (isinstance(stripped, str) and stripped.startswith(('[Console]', '[Hook ', '[Hook #')))

    def prepare(self, text, allow_auto_copy=False):
        with self.host.output_processing_lock:
            current, clipboard, translators, post = self.run_pre_translation(text)
        if current is None: return None
        def strip_marker(value):
            if isinstance(value, str):
                match = re.match(r'^\[Hook #?\d+\|\d+\]\s*(.*)$', value.strip(), re.DOTALL)
                if match:
                    return match.group(1) + ('\n' if value.endswith('\n') else '')
            return value
        internal = isinstance(current, str) and bool(re.match(r'^\[Hook #?\d+\|\d+\]\s*(.*)$', current.strip(), re.DOTALL))
        current = strip_marker(current); clipboard = strip_marker(clipboard)
        translator_input = current.strip() if isinstance(current, str) else current
        clipboard_text = clipboard.strip() if isinstance(clipboard, str) else clipboard
        candidates = []
        if not internal and self.translation_worthy(translator_input):
            for plugin in translators:
                try:
                    if not callable(getattr(plugin, 'should_translate_text', None)) or plugin.should_translate_text(translator_input): candidates.append(plugin)
                except Exception: logging.exception('Translation eligibility check failed: %s', getattr(plugin, 'name', type(plugin).__name__))
        incoming_preview = isinstance(text, str) and text.lstrip().startswith('[Hook')
        output_preview = isinstance(current, str) and current.lstrip().startswith('[Hook')
        return {'incoming': text, 'current_text': current, 'translator_input': translator_input, 'clipboard_text': clipboard_text,
                'translation_plugins': tuple(candidates), 'post_translation_plugins': tuple(post),
                'allow_auto_copy': allow_auto_copy or (incoming_preview and not output_preview and not internal)}

    @staticmethod
    def requires_translation(prepared): return bool(prepared['translation_plugins'])

    def complete(self, prepared):
        current = prepared['current_text']; display = current
        results = []
        for plugin in prepared['translation_plugins']:
            try:
                translated = plugin.translate_text(prepared['translator_input'])
                if translated: results.append((plugin.name, translated.strip()))
            except Exception: logging.exception('Translation plugin failed: %s', getattr(plugin, 'name', type(plugin).__name__))
        if len(results) == 1: display = f"{current.rstrip()}\n{results[0][1]}\n\n"
        elif results: display = f"{current.rstrip()}\n" + '\n'.join(f'[{name}] {value}' for name, value in results) + '\n\n'
        for plugin in prepared['post_translation_plugins']:
            try:
                display = plugin.process_text(display)
                if display is None: return None, None
            except Exception: logging.exception('Post-translation plugin failed: %s', getattr(plugin, 'name', type(plugin).__name__))
        return display, prepared['clipboard_text']

    def remember_context(self, prepared):
        for plugin in prepared['translation_plugins']:
            try:
                remember = getattr(plugin, 'remember_original_line', None)
                if callable(remember) and prepared['translator_input']: remember(prepared['translator_input'])
            except Exception: logging.exception('Failed to remember translation context for %s', getattr(plugin, 'name', type(plugin).__name__))
