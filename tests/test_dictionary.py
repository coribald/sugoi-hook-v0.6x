import json
import queue
import threading
import unittest

from dictionary_backend import JitendexDictionary, extract_redirect_targets
from plugins.overlay_window import DICTIONARY_LOOKUP_CHAR_PATTERN, OverlayWindowPlugin


def make_entry(expression, sequence_id, definitions=None):
    return {
        "expression": expression,
        "reading": expression,
        "term_tags": "",
        "rules": "",
        "score": 0,
        "sequence_id": sequence_id,
        "summary_text": "",
        "display_tags": "[]",
        "definitions_json": json.dumps(definitions),
    }


class DictionaryBackendTests(unittest.TestCase):
    def test_extract_redirect_target_from_jitendex_structure(self):
        definitions = [{
            "type": "structured-content",
            "content": {
                "tag": "div",
                "data": {"content": "redirect-glossary"},
                "content": [
                    "⟶",
                    {"tag": "a", "href": "?query=%E7%89%B9%E5%8A%B9&wildcards=off", "content": "特効"},
                ],
            },
        }]

        self.assertEqual(extract_redirect_targets(definitions), ["特効"])

    def test_redirect_expansion_respects_entry_limit(self):
        definitions = {
            "tag": "div",
            "data": {"content": "redirect-glossary"},
            "content": [
                {"tag": "a", "href": "?query=target-one", "content": "target-one"},
                {"tag": "a", "href": "?query=target-two", "content": "target-two"},
            ],
        }
        source = make_entry("source", 1, definitions)
        backend = JitendexDictionary.__new__(JitendexDictionary)
        backend._lookup_entries_for_term = lambda connection, target, allowed_pos, limit: [
            make_entry(f"{target}-a", 10, []),
            make_entry(f"{target}-b", 11, []),
        ]

        expanded = backend._expand_redirect_entries(None, [source], None, entries_per_match=2)

        self.assertEqual(len(expanded), 2)
        self.assertEqual([entry["expression"] for entry in expanded], ["target-one-a", "target-one-b"])


class QueuedApp:
    def __init__(self):
        self.callbacks = queue.Queue()

    def run_on_ui_thread(self, callback, *args):
        self.callbacks.put((callback, args))


class ReadyBackend:
    def __init__(self, release_lookup):
        self.release_lookup = release_lookup
        self.lookup_started = threading.Event()
        self.lookup_thread = None

    def get_status(self):
        return {"ready": True, "error": "", "progress_message": "Dictionary ready"}

    def lookup_run_covering_offset(self, run_text, local_offset):
        self.lookup_thread = threading.current_thread()
        self.lookup_started.set()
        self.release_lookup.wait(2)
        return {
            "match_start": 0,
            "match_end": 1,
            "matched_text": run_text,
            "entries": [],
            "matches": [],
        }


class FakeTextWidget:
    def index(self, position):
        return "1.0"

    def count(self, start, end, unit):
        return (0,)

    def get(self, start, end):
        return "猫"


class OverlayDictionaryTests(unittest.TestCase):
    def make_plugin(self, backend):
        plugin = OverlayWindowPlugin.__new__(OverlayWindowPlugin)
        plugin.app = QueuedApp()
        plugin.overlay = object()
        plugin.text_widget = FakeTextWidget()
        plugin.dictionary_backend = backend
        plugin.dictionary_lookup_char_pattern = DICTIONARY_LOOKUP_CHAR_PATTERN
        plugin._dictionary_lookup_generation = 0
        plugin._debug = lambda *args, **kwargs: None
        plugin.clear_dictionary_highlight = lambda: None
        plugin.set_dictionary_text = lambda text, tagged_sections=None: None
        plugin.highlighted = []
        plugin.rendered = []
        plugin.highlight_dictionary_match = lambda start, end, select_match=False: plugin.highlighted.append(
            (start, end, select_match)
        )
        plugin.render_dictionary_matches = plugin.rendered.append
        return plugin

    def test_lookup_runs_off_ui_thread_and_returns_through_dispatcher(self):
        release_lookup = threading.Event()
        backend = ReadyBackend(release_lookup)
        plugin = self.make_plugin(backend)

        plugin.lookup_text_at_coords(0, 0, select_match=True)

        self.assertTrue(backend.lookup_started.wait(1))
        self.assertIsNot(backend.lookup_thread, threading.current_thread())
        self.assertTrue(plugin.app.callbacks.empty())
        release_lookup.set()
        callback, args = plugin.app.callbacks.get(timeout=1)
        callback(*args)

        self.assertEqual(plugin.highlighted, [(0, 1, True)])
        self.assertEqual(len(plugin.rendered), 1)

    def test_stale_lookup_result_is_discarded(self):
        release_lookup = threading.Event()
        backend = ReadyBackend(release_lookup)
        plugin = self.make_plugin(backend)

        plugin.lookup_text_at_coords(0, 0)
        self.assertTrue(backend.lookup_started.wait(1))
        plugin._invalidate_dictionary_lookup()
        release_lookup.set()
        callback, args = plugin.app.callbacks.get(timeout=1)
        callback(*args)

        self.assertEqual(plugin.highlighted, [])
        self.assertEqual(plugin.rendered, [])


if __name__ == "__main__":
    unittest.main()
