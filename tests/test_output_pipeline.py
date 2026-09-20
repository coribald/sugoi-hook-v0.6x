import threading
import time
import unittest

from output_pipeline import OutputPipeline


class OutputPipelineTests(unittest.TestCase):
    def setUp(self):
        self.pipelines = []

    def tearDown(self):
        for pipeline in self.pipelines:
            pipeline.stop()

    def wait_for(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Timed out waiting for pipeline state")

    def test_preprocessing_is_lossless_and_delivers_inflight_plus_latest_pending(self):
        prepared = []
        completed = []
        delivered = []
        stale = []
        superseded = []
        first_translation_started = threading.Event()
        release_first_translation = threading.Event()

        def prepare(text, allow_auto_copy):
            prepared.append(text)
            return {"text": text, "allow_auto_copy": allow_auto_copy}

        def complete(bundle):
            completed.append(bundle["text"])
            if bundle["text"] == "A":
                first_translation_started.set()
                release_first_translation.wait(2.0)
            return bundle["text"].lower()

        pipeline = OutputPipeline(
            prepare=prepare,
            complete=complete,
            deliver=lambda result, bundle: delivered.append((result, bundle["text"])),
            on_stale=lambda bundle, generation, invalidated: stale.append((bundle["text"], invalidated)),
            on_superseded=lambda bundle, generation: superseded.append(bundle["text"]),
        )
        self.pipelines.append(pipeline)

        pipeline.submit("A")
        self.assertTrue(first_translation_started.wait(1.0))
        pipeline.submit("B")
        pipeline.submit("C")
        self.wait_for(lambda: prepared == ["A", "B", "C"])
        release_first_translation.set()
        self.wait_for(lambda: delivered == [("a", "A"), ("c", "C")])

        self.assertEqual(prepared, ["A", "B", "C"])
        self.assertEqual(completed, ["A", "C"])
        self.assertEqual(stale, [])
        self.assertEqual(superseded, ["A"])

    def test_nontranslation_output_does_not_supersede_openai_work(self):
        translation_started = threading.Event()
        release_translation = threading.Event()
        delivered = []

        def prepare(text, allow_auto_copy):
            return {"text": text}

        def complete(bundle):
            if bundle["text"] == "dialogue":
                translation_started.set()
                release_translation.wait(2.0)
            return bundle["text"]

        pipeline = OutputPipeline(
            prepare=prepare,
            complete=complete,
            deliver=lambda result, bundle: delivered.append(result),
            is_latest_only=lambda bundle: bundle["text"] != "status",
        )
        self.pipelines.append(pipeline)

        pipeline.submit("dialogue")
        self.assertTrue(translation_started.wait(1.0))
        pipeline.submit("status")
        self.wait_for(lambda: delivered == ["status"])
        release_translation.set()
        self.wait_for(lambda: delivered == ["status", "dialogue"])

    def test_invalidation_marks_inflight_translation_as_reset_stale(self):
        translation_started = threading.Event()
        release_translation = threading.Event()
        stale = []
        delivered = []

        def complete(bundle):
            translation_started.set()
            release_translation.wait(2.0)
            return bundle["text"]

        pipeline = OutputPipeline(
            prepare=lambda text, allow_auto_copy: {"text": text},
            complete=complete,
            deliver=lambda result, bundle: delivered.append(result),
            on_stale=lambda bundle, generation, invalidated: stale.append(invalidated),
        )
        self.pipelines.append(pipeline)

        pipeline.submit("old")
        self.assertTrue(translation_started.wait(1.0))
        pipeline.invalidate(clear_pending=True)
        release_translation.set()
        self.wait_for(lambda: stale == [True])

        self.assertEqual(delivered, [])

    def test_invalidation_drops_preprocessing_that_finishes_after_reset(self):
        prepare_started = threading.Event()
        release_prepare = threading.Event()
        completed = []
        delivered = []

        def prepare(text, allow_auto_copy):
            if text == "old":
                prepare_started.set()
                release_prepare.wait(2.0)
            return {"text": text}

        def complete(bundle):
            completed.append(bundle["text"])
            return bundle["text"]

        pipeline = OutputPipeline(
            prepare=prepare,
            complete=complete,
            deliver=lambda result, bundle: delivered.append(result),
        )
        self.pipelines.append(pipeline)

        pipeline.submit("old")
        self.assertTrue(prepare_started.wait(1.0))
        pipeline.invalidate(clear_pending=True)
        release_prepare.set()
        time.sleep(0.05)
        pipeline.submit("new")
        self.wait_for(lambda: delivered == ["new"])

        self.assertEqual(completed, ["new"])

    def test_cancelled_scheduled_callback_never_mutates_pipeline_state(self):
        callbacks = []
        pipeline = OutputPipeline(
            prepare=lambda text, allow_auto_copy: None,
            complete=lambda bundle: bundle,
            deliver=lambda result, bundle: None,
        )
        self.pipelines.append(pipeline)

        handle = pipeline.schedule_callback(20, lambda: callbacks.append("cancelled"))
        pipeline.cancel_callback(handle)
        pipeline.schedule_callback(20, lambda: callbacks.append(threading.current_thread().name))
        self.wait_for(lambda: len(callbacks) == 1)

        self.assertEqual(callbacks, ["output-preprocessing-worker"])


if __name__ == "__main__":
    unittest.main()
