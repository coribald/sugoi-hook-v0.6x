import sys
import threading
import time
import unittest

import SugoiHook_gui as gui
from output_pipeline import OutputPipeline

sys.stdout = gui.ORIGINAL_STDOUT
sys.stderr = gui.ORIGINAL_STDERR


class ProbePlugin:
    name = "Probe"
    enabled = True
    is_translation_plugin = False

    def __init__(self, display=None, clipboard=None):
        self.display = display
        self.clipboard = clipboard
        self.display_calls = 0
        self.clipboard_calls = 0

    def process_text(self, text):
        self.display_calls += 1
        return self.display if self.display is not None else text

    def process_clipboard_text(self, text):
        self.clipboard_calls += 1
        return self.clipboard if self.clipboard is not None else text


class TranslationProbe:
    name = "OpenAI Probe"
    enabled = True
    is_translation_plugin = True

    def __init__(self, translated="Translated line"):
        self.translated = translated

    def should_translate_text(self, text):
        return not text.startswith("[Console]")

    def translate_text(self, text):
        return self.translated


class DropPlugin:
    name = "Drop"
    enabled = True
    is_translation_plugin = False

    def process_text(self, text):
        return None

    def process_clipboard_text(self, text):
        return None


class FallbackTranslationProbe:
    name = "Fallback Probe"
    enabled = True
    is_translation_plugin = True


class GuiPipelineRegressionTests(unittest.TestCase):
    def make_app(self, plugins, order):
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        app.plugins = plugins
        app.plugin_order = order
        app.active_plugins = list(order)
        app.pipeline_debug_enabled = False
        app.output_processing_lock = threading.Lock()
        return app

    def test_clipboard_preprocessing_runs_once(self):
        probe = ProbePlugin()
        app = self.make_app({"probe.py": probe}, ["probe.py"])

        prepared = app.prepare_plugin_output_bundle("台詞\n", True)

        self.assertEqual(prepared["translator_input"], "台詞")
        self.assertEqual(probe.display_calls, 1)
        self.assertEqual(probe.clipboard_calls, 1)

    def test_pipeline_emits_detailed_stage_diagnostics(self):
        pre = ProbePlugin(display="Clean source\n", clipboard="Clipboard source\n")
        translator = TranslationProbe("English result")
        post = ProbePlugin(display="Final display\n")
        app = self.make_app(
            {"pre.py": pre, "translator.py": translator, "post.py": post},
            ["pre.py", "translator.py", "post.py"],
        )
        diagnostics = []
        app.log_pipeline = lambda stage, **fields: diagnostics.append((stage, fields))

        prepared = app.prepare_plugin_output_bundle("Raw source\n", True)
        completed = app.complete_plugin_output_bundle(prepared)

        self.assertEqual(completed, ("Final display\n", "Clipboard source"))
        stages = [stage for stage, _fields in diagnostics]
        self.assertEqual(stages, [
            "pre_translation.start",
            "pre_translation.plugin_result",
            "pre_translation.clipboard_plugin_result",
            "pre_translation.complete",
            "bundle.prepared",
            "translation.request",
            "translation.result",
            "bundle.translation_phase_complete",
            "post_translation.plugin_result",
            "output.summary",
        ])
        self.assertEqual(diagnostics[4][1]["translator_input"], "Clean source")
        self.assertEqual(diagnostics[5][1]["clipboard_source"], "Clipboard source")
        self.assertEqual(diagnostics[-1][1]["output_window_text"], "Final display\n")

    def test_pipeline_logs_empty_translation_and_post_drop(self):
        translator = TranslationProbe("")
        post = DropPlugin()
        app = self.make_app(
            {"translator.py": translator, "post.py": post},
            ["translator.py", "post.py"],
        )
        diagnostics = []
        app.log_pipeline = lambda stage, **fields: diagnostics.append((stage, fields))

        prepared = app.prepare_plugin_output_bundle("Source\n", False)
        completed = app.complete_plugin_output_bundle(prepared)

        self.assertEqual(completed, (None, None))
        stages = [stage for stage, _fields in diagnostics]
        self.assertIn("translation.empty", stages)
        self.assertIn("bundle.translation_phase_complete", stages)
        self.assertIn("post_translation.plugin_dropped", stages)
        self.assertNotIn("output.summary", stages)

    def test_pipeline_logs_display_and_clipboard_drops(self):
        drop = DropPlugin()
        app = self.make_app({"drop.py": drop}, ["drop.py"])
        diagnostics = []
        app.log_pipeline = lambda stage, **fields: diagnostics.append((stage, fields))

        prepared = app.prepare_plugin_output_bundle("Dropped source\n", False)

        self.assertIsNone(prepared)
        self.assertEqual([stage for stage, _fields in diagnostics], [
            "pre_translation.start",
            "pre_translation.plugin_dropped",
            "pre_translation.clipboard_plugin_dropped",
            "bundle.dropped_pre_translation",
        ])

    def test_console_output_does_not_enter_latest_only_translation(self):
        translator = TranslationProbe()
        app = self.make_app({"openai.py": translator}, ["openai.py"])

        prepared = app.prepare_plugin_output_bundle("[Console] attached\n", False)

        self.assertFalse(app.prepared_output_requires_translation(prepared))

    def test_fallback_translator_cannot_make_console_output_latest_only(self):
        translator = FallbackTranslationProbe()
        app = self.make_app({"fallback.py": translator}, ["fallback.py"])

        prepared = app.prepare_plugin_output_bundle("[Console] attached\n", False)

        self.assertFalse(app.prepared_output_requires_translation(prepared))

    def test_scheduled_callback_revalidates_epoch_after_plugin_lock(self):
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        app.output_processing_lock = threading.Lock()
        app.output_pipeline = OutputPipeline(
            prepare=lambda text, allow_auto_copy: None,
            complete=lambda prepared: prepared,
            deliver=lambda completed, prepared: None,
        )
        callback_ran = threading.Event()

        app.output_processing_lock.acquire()
        try:
            app.schedule_pipeline_callback(0, callback_ran.set)
            time.sleep(0.03)
            app.output_pipeline.invalidate(clear_pending=True)
        finally:
            app.output_processing_lock.release()
        time.sleep(0.03)
        app.output_pipeline.stop()

        self.assertFalse(callback_ran.is_set())

    def test_selected_dialogue_keeps_hook_identity_when_concat_owns_it(self):
        app = self.make_app({}, [])
        app.hooks_lock = threading.Lock()
        app.hooks = {"2": {"last_pipeline_sequence": 0}}
        app.selected_hook_id = "2"
        app.silent_auto_launch = False
        app.get_hook_concatenation_state = lambda: {
            "active": True,
            "hook_ids": ["2"],
        }
        routed = []
        app.append_output = lambda text, process_plugins, allow_auto_copy: routed.append(
            (text, process_plugins, allow_auto_copy)
        )

        route = app.route_hook_output("2", "分割された台詞", 7)

        self.assertEqual(route, "concatenation")
        self.assertEqual(routed, [("[Hook #2|7] 分割された台詞\n", True, False)])
        self.assertEqual(app.hooks["2"]["last_pipeline_sequence"], 7)

    def test_internal_hook_marker_cannot_leak_or_translate_after_concat_deactivation(self):
        translator = TranslationProbe()
        app = self.make_app({"openai.py": translator}, ["openai.py"])

        prepared = app.prepare_plugin_output_bundle("[Hook #2|7] 未処理の台詞\n", False)

        self.assertEqual(prepared["current_text"], "未処理の台詞\n")
        self.assertEqual(prepared["clipboard_text"], "未処理の台詞")
        self.assertFalse(prepared["allow_auto_copy"])
        self.assertFalse(app.prepared_output_requires_translation(prepared))

    def test_concat_transformation_promotes_auto_copy(self):
        concat = ProbePlugin(display="結合した台詞\n", clipboard="結合した台詞\n")
        translator = TranslationProbe()
        app = self.make_app(
            {"concat.py": concat, "openai.py": translator},
            ["concat.py", "openai.py"],
        )

        prepared = app.prepare_plugin_output_bundle("[Hook #2] 分割された台詞\n", False)

        self.assertTrue(prepared["allow_auto_copy"])
        self.assertTrue(app.prepared_output_requires_translation(prepared))
        self.assertEqual(prepared["translator_input"], "結合した台詞")


if __name__ == "__main__":
    unittest.main()
