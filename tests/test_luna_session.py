import subprocess
import threading
import time
import unittest

import SugoiHook_gui as gui
from luna_session import LunaProcessSession
from luna_controller import LunaController, parse_luna_output_line


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
    def make_controller(self, dispatch=lambda callback, *args: callback(*args), **callbacks):
        process_factory = callbacks.pop('process_factory', lambda *args, **kwargs: FakeProcess(wait_event=threading.Event()))
        return LunaController(
            gui.HookRegistry(), dispatch, process_factory=process_factory, **callbacks,
        )
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
        controller = self.make_controller()
        current = controller.start(["luna"], 42, "current.exe")
        stale = LunaProcessSession(FakeProcess(), 1, 41, "stale.exe")

        with self.assertRaises(RuntimeError):
            controller.send("select 1", session=stale)

        self.assertEqual(stale.process.stdin.writes, [])

    def test_unexpected_exit_clears_only_current_session(self):
        exits = []
        controller = self.make_controller(on_session_exit=lambda session, code, expected: exits.append((code, expected)))
        session = controller.start(["luna"], 42, "game.exe")

        controller.notify_exit(session, 5)

        self.assertIsNone(controller.session)
        self.assertEqual(exits, [(5, False)])

    def test_stale_exit_cannot_clear_newer_session(self):
        stale = LunaProcessSession(FakeProcess(), 1, 41, "stale.exe")
        controller = self.make_controller()
        current = controller.start(["luna"], 42, "current.exe")
        callback_ran = threading.Event()
        controller.add_exit_callback(stale, callback_ran.set)

        controller.notify_exit(stale, 0)

        self.assertIs(controller.session, current)
        self.assertTrue(callback_ran.is_set())

    def test_detach_returns_without_waiting_for_process_exit(self):
        release_wait = threading.Event()
        process = FakeProcess(wait_event=release_wait)
        controller = self.make_controller(process_factory=lambda *args, **kwargs: process)
        session = controller.start(["luna"], 42, "game.exe")

        callback_ran = threading.Event()
        started_at = time.monotonic()
        controller.add_exit_callback(session, callback_ran.set)
        controller.detach(session)
        elapsed = time.monotonic() - started_at

        self.assertLess(elapsed, 0.1)
        self.assertTrue(session.stop_started.is_set())
        self.assertFalse(callback_ran.is_set())
        release_wait.set()
        deadline = time.monotonic() + 1.0
        while controller.session is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNone(controller.session)
        self.assertTrue(callback_ran.is_set())

    def test_parse_luna_output_line_preserves_console_and_context_fields(self):
        self.assertEqual(parse_luna_output_line("[Console] attached\n"), ("console", "attached"))
        self.assertEqual(
            parse_luna_output_line("[#7|game.exe:EXBWX0@25C880:thread] text\n"),
            ("hook", ("7", "EXBWX0@25C880", "game.exe:EXBWX0@25C880:thread", "text")),
        )
        self.assertIsNone(parse_luna_output_line("unrecognized"))


if __name__ == "__main__":
    unittest.main()
