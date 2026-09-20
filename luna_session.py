from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass(eq=False)
class LunaProcessSession:
    process: Any
    generation: int
    target_pid: int
    process_name: str
    expected_stop: threading.Event = field(default_factory=threading.Event)
    exit_notified: threading.Event = field(default_factory=threading.Event)
    stop_started: threading.Event = field(default_factory=threading.Event)
    lifecycle_lock: threading.Lock = field(default_factory=threading.Lock)
    write_lock: threading.Lock = field(default_factory=threading.Lock)

    def is_running(self) -> bool:
        return self.process.poll() is None

    def send(self, command: str) -> None:
        with self.write_lock:
            if self.expected_stop.is_set() or not self.is_running() or self.process.stdin is None:
                raise RuntimeError("Luna CLI process is not running")
            self.process.stdin.write(command.rstrip("\n") + "\n")
            self.process.stdin.flush()

    def request_stop(self) -> bool:
        with self.lifecycle_lock:
            self.expected_stop.set()
            if self.stop_started.is_set():
                return False
            self.stop_started.set()
            return True

    def terminate(self, timeout: float = 2.0) -> int | None:
        if self.is_running():
            try:
                with self.write_lock:
                    if self.process.stdin is not None:
                        self.process.stdin.write(f"detach -P{self.target_pid}\n")
                        self.process.stdin.flush()
            except Exception:
                pass
        if self.is_running():
            try:
                self.process.terminate()
                return self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()
                return self.process.wait(timeout=timeout)
            except Exception:
                try:
                    self.process.kill()
                    return self.process.wait(timeout=timeout)
                except Exception:
                    return self.process.poll()
        return self.process.poll()
