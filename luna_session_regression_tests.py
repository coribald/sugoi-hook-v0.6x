import subprocess
import threading
import time
import unittest

import SugoiHook_gui as gui
from luna_session import LunaProcessSession


gui.sys.stdout = gui.ORIGINAL_STDOUT
gui.sys.stderr = gui.ORIGINAL_STDERR


class FakeStdin:
    def __init__(self):
        self.writes = []
        self.flush_count = 0

    def write(self, value):
        self.writes.append(value)

    def flush(self):
        self.flush_count += 1


class FakeProcess:
    def __init__(self, wait_event=None, timeout_once=False):
        self.stdin = FakeStdin()
        self.stdout = None
        self.stderr = None
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.wait_event = wait_event
        self.timeout_once = timeout_once

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self.returncode = -9
        if self.wait_event:
            self.wait_event.set()

    def wait(self, timeout=None):
        if self.timeout_once:
            self.timeout_once = False
            raise subprocess.TimeoutExpired("fake-luna", timeout)
        if self.wait_event:
            self.wait_event.wait(timeout)
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class LunaProcessSessionTests(unittest.TestCase):
    def test_send_is_bound_to_running_process(self):
        process = FakeProcess()
        session = LunaProcessSession(process, 1, 42, "game.exe")

        session.send("select 7")

        self.assertEqual(process.stdin.writes, ["select 7\n"])
        self.assertEqual(process.stdin.flush_count, 1)
        session.request_stop()
        with self.assertRaises(RuntimeError):
            session.send("select 8")

    def test_terminate_sends_detach_and_kills_after_timeout(self):
        process = FakeProcess(timeout_once=True)
        session = LunaProcessSession(process, 1, 42, "game.exe")
        session.request_stop()

        return_code = session.terminate(timeout=0.01)

        self.assertEqual(process.stdin.writes, ["detach -P42\n"])
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertEqual(return_code, -9)

    def test_stale_session_cannot_receive_commands(self):
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        app.luna_session_lock = threading.RLock()
        current = LunaProcessSession(FakeProcess(), 2, 42, "current.exe")
        stale = LunaProcessSession(FakeProcess(), 1, 41, "stale.exe")
        app.luna_session = current

        with self.assertRaises(RuntimeError):
            app.send_luna_command("select 1", session=stale)

        self.assertEqual(stale.process.stdin.writes, [])

    def test_unexpected_exit_clears_only_current_session(self):
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        app.luna_session_lock = threading.RLock()
        session = LunaProcessSession(FakeProcess(), 2, 42, "game.exe")
        app.luna_session = session
        app.cli_process = session.process
        app.is_reading = True
        app.luna_exit_callbacks = {}
        app.attached_pid = 42
        app.selected_hook_id = "7"
        app.hooks_lock = threading.Lock()
        app.hooks = {"7": {"texts": ["line"]}}

        app.finalize_luna_session_exit(session, 5)

        self.assertIsNone(app.get_luna_session())
        self.assertIsNone(app.cli_process)
        self.assertFalse(app.is_reading)
        self.assertIsNone(app.attached_pid)
        self.assertEqual(app.hooks, {})

    def test_stale_exit_cannot_clear_newer_session(self):
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        app.luna_session_lock = threading.RLock()
        stale = LunaProcessSession(FakeProcess(), 1, 41, "stale.exe")
        current = LunaProcessSession(FakeProcess(), 2, 42, "current.exe")
        callback_ran = threading.Event()
        app.luna_session = current
        app.cli_process = current.process
        app.is_reading = True
        app.luna_exit_callbacks = {stale.generation: [callback_ran.set]}
        app.attached_pid = 42

        app.finalize_luna_session_exit(stale, 0)

        self.assertIs(app.get_luna_session(), current)
        self.assertIs(app.cli_process, current.process)
        self.assertEqual(app.attached_pid, 42)
        self.assertTrue(callback_ran.is_set())

    def test_detach_returns_without_waiting_for_process_exit(self):
        release_wait = threading.Event()
        process = FakeProcess(wait_event=release_wait)
        session = LunaProcessSession(process, 1, 42, "game.exe")
        app = gui.SugoiHookGUI.__new__(gui.SugoiHookGUI)
        app.luna_session_lock = threading.RLock()
        app.luna_session = session
        app.cli_process = process
        app.is_reading = True
        app.luna_exit_callbacks = {}
        app.attached_pid = 42
        app.selected_hook_id = "7"
        app.hooks_lock = threading.Lock()
        app.hooks = {"7": {"texts": ["line"]}}
        app.run_on_ui_thread = lambda callback, *args: callback(*args)

        callback_ran = threading.Event()
        started_at = time.monotonic()
        app.detach_process(on_complete=callback_ran.set, notify=False)
        elapsed = time.monotonic() - started_at

        self.assertLess(elapsed, 0.1)
        self.assertTrue(session.stop_started.is_set())
        self.assertFalse(callback_ran.is_set())
        release_wait.set()
        deadline = time.monotonic() + 1.0
        while app.get_luna_session() is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNone(app.get_luna_session())
        self.assertIsNone(app.attached_pid)
        self.assertTrue(callback_ran.is_set())


if __name__ == "__main__":
    unittest.main()
