"""Luna CLI process ownership, output parsing, and session lifetime."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import threading
import time
from typing import Any, Callable

from hook_registry import HookRegistry
from luna_session import LunaProcessSession


HOOK_LINE_PATTERN = re.compile(r"^\[#(\d+)\|([^\]]+)\] (.*)$")
CONSOLE_LINE_PATTERN = re.compile(r"^\[Console\] (.+)$")


@dataclass(frozen=True)
class LunaHookTextEvent:
    hook_id: str
    thread_name: str
    context_info: str
    text: str
    event_sequence: int
    is_new_hook: bool


def parse_luna_output_line(line: str) -> tuple[str, Any] | None:
    """Parse one Luna output line without depending on Tk or process state."""
    line = line.strip()
    if not line:
        return None
    console_match = CONSOLE_LINE_PATTERN.match(line)
    if console_match:
        return "console", console_match.group(1)
    hook_match = HOOK_LINE_PATTERN.match(line)
    if not hook_match:
        return None
    hook_id, context_info, text = hook_match.groups()
    context_parts = context_info.split(":")
    thread_name = context_parts[-2] if len(context_parts) >= 2 else "Unknown"
    return "hook", (hook_id, thread_name, context_info, text)


class LunaController:
    """Own one current Luna session and emit UI-safe domain callbacks."""

    def __init__(
        self,
        hook_registry: HookRegistry,
        dispatch_ui: Callable[..., None],
        *,
        process_factory: Callable[..., Any],
        session_factory: Callable[..., LunaProcessSession] = LunaProcessSession,
        output_lock: threading.RLock | None = None,
        max_hook_texts: int = 3,
        on_console: Callable[[str], None] | None = None,
        on_hook_text: Callable[[LunaHookTextEvent], None] | None = None,
        on_hook_discovered: Callable[[str, str], None] | None = None,
        on_hook_preview: Callable[[str, str], None] | None = None,
        on_session_exit: Callable[[LunaProcessSession, int, bool], None] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.hook_registry = hook_registry
        self.dispatch_ui = dispatch_ui
        self.process_factory = process_factory
        self.session_factory = session_factory
        self.output_lock = output_lock or threading.RLock()
        self.max_hook_texts = max_hook_texts
        self.on_console = on_console
        self.on_hook_text = on_hook_text
        self.on_hook_discovered = on_hook_discovered
        self.on_hook_preview = on_hook_preview
        self.on_session_exit = on_session_exit
        self.logger = logger or logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._session: LunaProcessSession | None = None
        self._generation = 0
        self._exit_callbacks: dict[int, list[Callable[[], None]]] = {}

    @property
    def session(self) -> LunaProcessSession | None:
        with self._lock:
            return self._session

    @property
    def process(self) -> Any | None:
        session = self.session
        return session.process if session else None

    @property
    def is_reading(self) -> bool:
        return self.session is not None

    def is_current(self, session: LunaProcessSession) -> bool:
        with self._lock:
            return self._session is session

    def send(self, command: str, session: LunaProcessSession | None = None) -> None:
        target = session or self.session
        if target is None or not self.is_current(target):
            raise RuntimeError("No active Luna CLI session")
        target.send(command)

    def start(
        self, command: list[str], target_pid: int, process_name: str, *, start_workers: bool = True,
        **process_options: Any,
    ) -> LunaProcessSession:
        process = self.process_factory(command, **process_options)
        with self._lock:
            self._generation += 1
            session = self.session_factory(process, self._generation, int(target_pid), str(process_name))
            self._session = session
        try:
            session.send(f"attach -P{target_pid}")
        except Exception:
            session.request_stop()
            try:
                session.terminate()
            except Exception:
                self.logger.exception("Failed to terminate Luna session after attach command failure")
            finally:
                with self._lock:
                    if self._session is session:
                        self._session = None
            raise
        if start_workers:
            self.start_workers(session)
        return session

    def add_exit_callback(self, session: LunaProcessSession, callback: Callable[[], None]) -> None:
        with self._lock:
            self._exit_callbacks.setdefault(session.generation, []).append(callback)

    def detach(self, session: LunaProcessSession | None = None) -> bool:
        target = session or self.session
        if target is None:
            return False
        if not self.is_current(target):
            return False
        if not target.request_stop():
            return False
        threading.Thread(target=self._stop_session, args=(target,), name=f"luna-stop-{target.generation}", daemon=True).start()
        return True

    def start_workers(self, session: LunaProcessSession) -> None:
        """Begin readers only after the caller has finished attach-state setup."""
        if not self.is_current(session):
            return
        for target, name in ((self.read_output, "stdout"), (self.read_stderr, "stderr"), (self.watch_process, "watch")):
            threading.Thread(target=target, args=(session,), name=f"luna-{name}-{session.generation}", daemon=True).start()

    def read_output(self, session: LunaProcessSession) -> None:
        process = session.process
        while self.is_current(session) and process.stdout:
            try:
                line = process.stdout.readline()
                if not line:
                    break
                parsed = parse_luna_output_line(line)
                if parsed is None:
                    continue
                kind, payload = parsed
                if kind == "console":
                    if self.on_console:
                        self.dispatch_ui(self.on_console, payload)
                    continue
                hook_id, thread_name, context_info, text = payload
                with self.output_lock:
                    is_new_hook, event_sequence = self.hook_registry.record_text(
                        hook_id, thread_name, context_info, text, time.monotonic(), self.max_hook_texts
                    )
                    event = LunaHookTextEvent(hook_id, thread_name, context_info, text, event_sequence, is_new_hook)
                    if self.on_hook_text:
                        self.on_hook_text(event)
                if is_new_hook and self.on_hook_discovered:
                    self.dispatch_ui(self.on_hook_discovered, hook_id, thread_name)
                if self.on_hook_preview:
                    self.dispatch_ui(self.on_hook_preview, hook_id, text)
            except Exception:
                if self.is_current(session) and not session.expected_stop.is_set():
                    self.logger.exception("Luna stdout reader failed for generation %s", session.generation)
                break

    def read_stderr(self, session: LunaProcessSession) -> None:
        stream = session.process.stderr
        if stream is None:
            return
        try:
            while line := stream.readline():
                if stripped := line.strip():
                    self.logger.warning("[LUNA STDERR][generation=%s] %s", session.generation, stripped)
        except Exception:
            if not session.expected_stop.is_set():
                self.logger.exception("Luna stderr reader failed for generation %s", session.generation)

    def watch_process(self, session: LunaProcessSession) -> None:
        try:
            return_code = session.process.wait()
        except Exception:
            return_code = session.process.poll()
        self.notify_exit(session, return_code)

    def _stop_session(self, session: LunaProcessSession) -> None:
        self.notify_exit(session, session.terminate())

    def notify_exit(self, session: LunaProcessSession, return_code: int | None) -> None:
        with self._lock:
            if session.exit_notified.is_set():
                return
            session.exit_notified.set()
        self.dispatch_ui(self._finalize_exit, session, return_code if return_code is not None else -1)

    def _finalize_exit(self, session: LunaProcessSession, return_code: int) -> None:
        with self._lock:
            callbacks = self._exit_callbacks.pop(session.generation, [])
            current = self._session is session
            if current:
                self._session = None
        if current and self.on_session_exit:
            self.on_session_exit(session, return_code, session.expected_stop.is_set())
        for callback in callbacks:
            callback()
