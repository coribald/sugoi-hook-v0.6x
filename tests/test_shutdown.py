from collections import deque
import threading
import unittest
from unittest.mock import patch

import SugoiHook_gui as gui


class FailingPipeline:
    def stop(self):
        raise RuntimeError("pipeline stop failed")


class RecordingRoot:
    def __init__(self):
        self.calls = []

    def quit(self):
        self.calls.append("quit")
        raise RuntimeError("quit failed")

    def destroy(self):
        self.calls.append("destroy")


class ShutdownTests(unittest.TestCase):
    def test_shutdown_continues_after_independent_cleanup_failures(self):
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        app.output_pipeline = FailingPipeline()
        app.output_processing_lock = threading.RLock()
        app.shutdown_plugin_instances = lambda: (_ for _ in ()).throw(RuntimeError("plugin shutdown failed"))
        app.tray_icon = None
        app.ui_callback_lock = threading.Lock()
        app.ui_callback_shutdown = False
        app.ui_callback_queue = deque([("callback", ())])
        app.root = RecordingRoot()

        with patch.object(gui, "TRAY_AVAILABLE", False), self.assertLogs(level="ERROR") as logs:
            app.finish_quit_app()

        self.assertTrue(app.ui_callback_shutdown)
        self.assertEqual(list(app.ui_callback_queue), [])
        self.assertEqual(app.root.calls, ["quit", "destroy"])
        self.assertTrue(any("Failed to stop output pipeline" in message for message in logs.output))
        self.assertTrue(any("Failed to shut down plugins" in message for message in logs.output))
        self.assertTrue(any("Failed to quit Tk mainloop" in message for message in logs.output))


if __name__ == "__main__":
    unittest.main()
