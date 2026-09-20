from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ScheduledPipelineCallback:
    timer: threading.Timer
    cancelled: threading.Event


class OutputPipeline:
    def __init__(
        self,
        prepare: Callable[[str, bool], Any],
        complete: Callable[[Any], Any],
        deliver: Callable[[Any, Any], None],
        is_latest_only: Callable[[Any], bool] | None = None,
        on_error: Callable[[str, Exception], None] | None = None,
        on_stale: Callable[[Any, int, bool], None] | None = None,
        on_superseded: Callable[[Any, int], None] | None = None,
    ):
        self.prepare = prepare
        self.complete = complete
        self.deliver = deliver
        self.is_latest_only = is_latest_only or (lambda prepared: True)
        self.on_error = on_error
        self.on_stale = on_stale
        self.on_superseded = on_superseded
        self._ingress_condition = threading.Condition()
        self._ingress_queue = deque()
        self._translation_condition = threading.Condition()
        self._translation_pending = None
        self._latest_generation = 0
        self._invalidation_epoch = 0
        self._shutdown = False
        self._preprocessing_thread = threading.Thread(
            target=self._preprocessing_worker,
            name="output-preprocessing-worker",
            daemon=True,
        )
        self._translation_thread = threading.Thread(
            target=self._translation_worker,
            name="output-translation-worker",
            daemon=True,
        )
        self._preprocessing_thread.start()
        self._translation_thread.start()

    def submit(self, text: str, allow_auto_copy: bool = False, front: bool = False) -> None:
        with self._translation_condition:
            epoch = self._invalidation_epoch
        request = ("text", text, allow_auto_copy, epoch)
        with self._ingress_condition:
            if self._shutdown:
                return
            if front:
                self._ingress_queue.appendleft(request)
            else:
                self._ingress_queue.append(request)
            self._ingress_condition.notify()

    def submit_callback(self, callback: Callable[[], None], front: bool = False, epoch: int | None = None) -> None:
        if epoch is None:
            with self._translation_condition:
                epoch = self._invalidation_epoch
        request = ("callback", callback, False, epoch)
        with self._ingress_condition:
            if self._shutdown:
                return
            if front:
                self._ingress_queue.appendleft(request)
            else:
                self._ingress_queue.append(request)
            self._ingress_condition.notify()

    def schedule_callback(self, delay_ms: int, callback: Callable[[], None]) -> ScheduledPipelineCallback:
        cancelled = threading.Event()
        with self._translation_condition:
            epoch = self._invalidation_epoch

        def enqueue_callback() -> None:
            if cancelled.is_set():
                return

            def invoke_if_current() -> None:
                if not cancelled.is_set():
                    callback()

            self.submit_callback(invoke_if_current, epoch=epoch)

        timer = threading.Timer(max(0, delay_ms) / 1000.0, enqueue_callback)
        timer.daemon = True
        handle = ScheduledPipelineCallback(timer=timer, cancelled=cancelled)
        timer.start()
        return handle

    def cancel_callback(self, handle: ScheduledPipelineCallback | None) -> None:
        if handle is None:
            return
        handle.cancelled.set()
        handle.timer.cancel()

    def get_invalidation_epoch(self) -> int:
        with self._translation_condition:
            return self._invalidation_epoch

    def is_epoch_current(self, epoch: int) -> bool:
        with self._translation_condition:
            return not self._shutdown and epoch == self._invalidation_epoch

    def invalidate(self, clear_pending: bool = False) -> None:
        with self._translation_condition:
            self._latest_generation += 1
            self._invalidation_epoch += 1
            if clear_pending:
                self._translation_pending = None
            self._translation_condition.notify_all()
        if clear_pending:
            with self._ingress_condition:
                self._ingress_queue.clear()

    def stop(self) -> None:
        with self._ingress_condition:
            self._shutdown = True
            self._ingress_queue.clear()
            self._ingress_condition.notify_all()
        with self._translation_condition:
            self._latest_generation += 1
            self._invalidation_epoch += 1
            self._translation_pending = None
            self._translation_condition.notify_all()

    def _preprocessing_worker(self) -> None:
        while True:
            with self._ingress_condition:
                while not self._shutdown and not self._ingress_queue:
                    self._ingress_condition.wait()
                if self._shutdown:
                    return
                request_type, payload, allow_auto_copy, epoch = self._ingress_queue.popleft()

            with self._translation_condition:
                if epoch != self._invalidation_epoch:
                    continue

            if request_type == "callback":
                try:
                    payload()
                except Exception as exc:
                    self._report_error("pipeline_callback", exc)
                continue

            try:
                prepared = self.prepare(payload, allow_auto_copy)
            except Exception as exc:
                self._report_error("preprocessing", exc)
                continue

            if prepared is None:
                continue

            if not self.is_latest_only(prepared):
                try:
                    completed = self.complete(prepared)
                except Exception as exc:
                    self._report_error("completion", exc)
                    continue
                with self._translation_condition:
                    if epoch != self._invalidation_epoch:
                        continue
                try:
                    self.deliver(completed, prepared)
                except Exception as exc:
                    self._report_error("delivery", exc)
                continue

            with self._translation_condition:
                if epoch != self._invalidation_epoch:
                    continue
                self._latest_generation += 1
                generation = self._latest_generation
                self._translation_pending = (generation, epoch, prepared)
                self._translation_condition.notify()

    def _translation_worker(self) -> None:
        while True:
            with self._translation_condition:
                while not self._shutdown and self._translation_pending is None:
                    self._translation_condition.wait()
                if self._shutdown:
                    return
                generation, epoch, prepared = self._translation_pending
                self._translation_pending = None

            try:
                completed = self.complete(prepared)
            except Exception as exc:
                self._report_error("translation", exc)
                continue

            with self._translation_condition:
                invalidated = epoch != self._invalidation_epoch
                superseded = generation != self._latest_generation

            if invalidated:
                if self.on_stale is not None:
                    try:
                        self.on_stale(prepared, generation, True)
                    except Exception as exc:
                        self._report_error("stale_callback", exc)
                continue

            if superseded and self.on_superseded is not None:
                try:
                    self.on_superseded(prepared, generation)
                except Exception as exc:
                    self._report_error("superseded_callback", exc)

            try:
                self.deliver(completed, prepared)
            except Exception as exc:
                self._report_error("delivery", exc)

    def _report_error(self, stage: str, exc: Exception) -> None:
        if self.on_error is not None:
            try:
                self.on_error(stage, exc)
            except Exception:
                pass
