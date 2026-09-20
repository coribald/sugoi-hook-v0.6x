"""Thread-safe dispatch of callbacks onto the Tk main thread."""

from collections import deque
import logging
import threading
from typing import Any, Callable, Deque


class UIThreadDispatcher:
    """Own the callback queue and Tk polling lifecycle for one root window."""

    def __init__(
        self,
        root: Any,
        *,
        poll_interval_ms: int = 10,
        ui_thread: threading.Thread | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._root = root
        self._poll_interval_ms = poll_interval_ms
        self._ui_thread = ui_thread or threading.main_thread()
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._callbacks: Deque[tuple[Callable[..., Any], tuple[Any, ...]]] = deque()
        self._stopped = False

    def start(self) -> None:
        """Schedule the first Tk-thread queue drain."""
        with self._lock:
            if self._stopped:
                return
        self._root.after(self._poll_interval_ms, self.drain)

    def dispatch(self, callback: Callable[..., Any], *args: Any) -> None:
        """Run now on the UI thread, otherwise queue work in FIFO order."""
        if threading.current_thread() is self._ui_thread:
            callback(*args)
            return
        with self._lock:
            if not self._stopped:
                self._callbacks.append((callback, args))

    def drain(self) -> None:
        """Run queued callbacks and schedule the next UI-thread poll."""
        with self._lock:
            callbacks = list(self._callbacks)
            self._callbacks.clear()
        for callback, args in callbacks:
            try:
                callback(*args)
            except Exception:
                self._logger.exception("UI callback failed")
        with self._lock:
            if self._stopped:
                return
            self._root.after(self._poll_interval_ms, self.drain)

    def stop(self) -> None:
        """Reject later callbacks and discard any queued work."""
        with self._lock:
            self._stopped = True
            self._callbacks.clear()
