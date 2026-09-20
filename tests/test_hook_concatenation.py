import time
import unittest

from plugins.hook_concatenation import HookConcatenationPlugin


class FakeApp:
    def __init__(self):
        self.callbacks = []
        self.cancelled = set()
        self.outputs = []
        self.hooks = {}

    def schedule_pipeline_callback(self, wait_ms, callback):
        handle = len(self.callbacks) + 1
        self.callbacks.append((wait_ms, callback))
        return handle

    def cancel_pipeline_callback(self, handle):
        self.cancelled.add(handle)

    def run_callback(self, handle):
        if handle not in self.cancelled:
            self.callbacks[handle - 1][1]()

    def submit_output_processing(self, text, allow_auto_copy=False, front=False):
        self.outputs.append((text, allow_auto_copy, front))

    def get_hooks_snapshot(self):
        return {
            str(hook_id): dict(hook_info)
            for hook_id, hook_info in self.hooks.items()
        }

    def mark_hook_event_processed(self, hook_id, event_sequence):
        hook_info = self.hooks.get(str(hook_id))
        if hook_info is not None:
            hook_info["last_processed_sequence"] = event_sequence


class HookConcatenationRegressionTests(unittest.TestCase):
    def test_default_dialogue_continuation_window_is_450ms(self):
        plugin = HookConcatenationPlugin()

        self.assertEqual(plugin._state["dialogue_continuation_window_ms"], 450)

    def make_plugin(self, prefixes=""):
        app = FakeApp()
        plugin = HookConcatenationPlugin()
        plugin.app = app
        plugin.set_setting("enabled_mode", True)
        plugin.set_setting("dialogue_hook_id", "2")
        plugin.set_setting("prefix_hook_ids", prefixes)
        plugin.set_setting("speaker_wait_ms", 150)
        plugin.set_setting("dialogue_continuation_window_ms", 1200)
        plugin.set_setting("burst_stabilization_enabled", False)
        return plugin, app

    def test_narration_chunks_merge_before_translation(self):
        plugin, app = self.make_plugin()

        self.assertIsNone(plugin.process_text("[Hook #2] 皆がそれぞれの方法で、形も大きさもわからない何かを求めて、\n"))
        first_handle = plugin._state["pending_timer_id"]
        self.assertEqual(app.callbacks[first_handle - 1][0], 1200)
        plugin._state["pending_dialogue_updated_at"] -= 1.045

        self.assertIsNone(plugin.process_text("[Hook #2] 深夜の宝探しに没頭する。\n"))
        second_handle = plugin._state["pending_timer_id"]
        self.assertIn(first_handle, app.cancelled)
        self.assertNotEqual(first_handle, second_handle)

        app.run_callback(second_handle)

        self.assertEqual(
            app.outputs,
            [("皆がそれぞれの方法で、形も大きさもわからない何かを求めて、深夜の宝探しに没頭する。\n", True, True)],
        )

    def test_rapid_dialogue_from_same_speaker_merges_before_translation(self):
        plugin, app = self.make_plugin("1")

        self.assertIsNone(plugin.process_text("[Hook #1] アリス\n"))
        self.assertIsNone(plugin.process_text("[Hook #2] 一つ目の文。\n"))
        self.assertIsNone(plugin.process_text("[Hook #1] アリス\n"))
        self.assertIsNone(plugin.process_text("[Hook #2] 二つ目の文。\n"))
        resolution_handle = plugin._state["pending_timer_id"]
        app.run_callback(resolution_handle)
        emit_handle = plugin._state["pending_timer_id"]
        app.run_callback(emit_handle)

        self.assertEqual(app.outputs, [("アリス一つ目の文。二つ目の文。\n", True, True)])

    def test_dialogue_before_changed_speaker_prefix_is_not_merged_with_previous_speaker(self):
        plugin, app = self.make_plugin("1")

        self.assertIsNone(plugin.process_text("[Hook #1] タイラ\n"))
        self.assertIsNone(plugin.process_text("[Hook #2] タイラの台詞。\n"))
        self.assertIsNone(plugin.process_text("[Hook #2] ミアの台詞。\n"))
        output = plugin.process_text("[Hook #1] ミア\n")
        clipboard = plugin.process_clipboard_text("[Hook #1] ミア\n")

        self.assertEqual(output, "タイラタイラの台詞。\n")
        self.assertEqual(clipboard, "タイラタイラの台詞。\n")
        handle = plugin._state["pending_timer_id"]
        app.run_callback(handle)
        self.assertEqual(app.outputs, [("ミアミアの台詞。\n", True, True)])

    def test_different_speaker_flushes_previous_dialogue_before_starting_next(self):
        plugin, app = self.make_plugin("1")

        self.assertIsNone(plugin.process_text("[Hook #1] アリス\n"))
        self.assertIsNone(plugin.process_text("[Hook #2] アリスの台詞。\n"))
        output = plugin.process_text("[Hook #1] ボブ\n")
        clipboard = plugin.process_clipboard_text("[Hook #1] ボブ\n")

        self.assertEqual(output, "アリスアリスの台詞。\n")
        self.assertEqual(clipboard, "アリスアリスの台詞。\n")
        self.assertIsNone(plugin.process_text("[Hook #2] ボブの台詞。\n"))
        handle = plugin._state["pending_timer_id"]
        app.run_callback(handle)
        self.assertEqual(app.outputs, [("ボブボブの台詞。\n", True, True)])

    def test_dialogue_only_clipboard_stays_separate_from_combined_display(self):
        plugin, app = self.make_plugin("1")
        plugin.set_setting("clipboard_output_mode", "dialogue_only")

        self.assertIsNone(plugin.process_text("[Hook #1] アリス\n"))
        self.assertIsNone(plugin.process_text("[Hook #2] 「おはよう。」\n"))
        handle = plugin._state["pending_timer_id"]
        app.run_callback(handle)
        emitted_text = app.outputs[0][0]
        output = plugin.process_text(emitted_text)
        clipboard = plugin.process_clipboard_text(emitted_text)

        self.assertEqual(output, "アリス「おはよう。」\n")
        self.assertEqual(clipboard, "おはよう。\n")

    def test_post_burst_recovery_accepts_fresh_narration_without_prefix(self):
        plugin, app = self.make_plugin("1")
        plugin._state["post_burst_recovery_active"] = True

        self.assertIsNone(plugin.process_text("[Hook #2] 静かな語りの続き。\n"))
        self.assertFalse(plugin._state["post_burst_recovery_active"])
        handle = plugin._state["pending_timer_id"]
        app.run_callback(handle)

        self.assertEqual(app.outputs, [("静かな語りの続き。\n", True, True)])

    def test_burst_suppression_recovers_on_fresh_prefix_dialogue_pair(self):
        plugin, app = self.make_plugin("1")
        plugin.set_setting("burst_stabilization_enabled", True)
        plugin.set_setting("burst_line_threshold", 2)

        plugin.process_text("[Hook #1] A\n")
        plugin.process_text("[Hook #2] one\n")
        plugin.process_clipboard_text("[Hook #2] one\n")
        plugin.process_text("[Hook #1] B\n")
        self.assertIsNone(plugin.process_text("[Hook #2] two\n"))
        self.assertTrue(plugin._state["burst_suppression_active"])

        plugin._release_burst_suppression()
        self.assertTrue(plugin._state["post_burst_recovery_active"])
        self.assertIsNone(plugin.process_text("[Hook #1] C\n"))
        self.assertIsNone(plugin.process_text("[Hook #2] fresh\n"))
        handle = plugin._state["pending_timer_id"]
        app.run_callback(handle)

        self.assertEqual(app.outputs, [("Cfresh\n", True, True)])
        self.assertFalse(plugin._state["post_burst_recovery_active"])

    def test_prefix_timeout_defers_to_dialogue_already_queued_in_pipeline(self):
        plugin, app = self.make_plugin("1")

        self.assertIsNone(plugin.process_text("[Hook #1] アリス\n"))
        prefix_handle = plugin._state["pending_timer_id"]
        now = time.monotonic()
        app.hooks["2"] = {
            "latest_text": "順番待ちの台詞。",
            "last_seen_monotonic": now,
            "latest_event_sequence": 7,
            "last_pipeline_sequence": 7,
            "last_processed_sequence": 0,
            "latest_event_snapshot": ("順番待ちの台詞。", now, 7),
        }

        app.run_callback(prefix_handle)

        self.assertEqual(app.outputs, [])
        deferred_handle = plugin._state["pending_timer_id"]
        self.assertNotEqual(prefix_handle, deferred_handle)
        self.assertIsNone(plugin.process_text("[Hook #2|7] 順番待ちの台詞。\n"))
        final_handle = plugin._state["pending_timer_id"]
        app.run_callback(final_handle)

        self.assertEqual(app.outputs, [("アリス順番待ちの台詞。\n", True, True)])
        self.assertEqual(app.hooks["2"]["last_processed_sequence"], 7)
        self.assertIn(deferred_handle, app.cancelled)

    def test_prefix_only_timeout_recovers_only_fresh_dialogue(self):
        plugin, app = self.make_plugin("1")

        self.assertIsNone(plugin.process_text("[Hook #1] アリス\n"))
        handle = plugin._state["pending_timer_id"]
        prefix_started_at = plugin._state["pending_prefix_started_at"]
        app.hooks["2"] = {
            "latest_text": "遅れて届いた台詞。",
            "last_seen_monotonic": prefix_started_at + 0.01,
        }

        app.run_callback(handle)

        self.assertEqual(app.outputs, [("アリス遅れて届いた台詞。\n", True, True)])

    def test_prefix_only_timeout_does_not_reuse_stale_dialogue(self):
        plugin, app = self.make_plugin("1")

        self.assertIsNone(plugin.process_text("[Hook #1] アリス\n"))
        handle = plugin._state["pending_timer_id"]
        prefix_started_at = plugin._state["pending_prefix_started_at"]
        app.hooks["2"] = {
            "latest_text": "前の台詞。",
            "last_seen_monotonic": prefix_started_at - 0.01,
        }

        app.run_callback(handle)

        self.assertEqual(app.outputs, [("アリス\n", True, True)])


if __name__ == "__main__":
    unittest.main()
