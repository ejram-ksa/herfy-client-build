from __future__ import annotations

import threading
import time
import unittest

from runtime.services.lifecycle import BackgroundScheduler


class FakeClock:
    def __init__(self):
        self.value = 0.0
    def __call__(self):
        return self.value
    def advance(self, seconds):
        self.value += seconds


class BackgroundSchedulerTests(unittest.TestCase):
    def test_register_and_run_due_once(self):
        clock = FakeClock()
        events = []
        scheduler = BackgroundScheduler(clock=clock)
        scheduler.register("sync", 10, lambda: events.append("sync"))
        self.assertEqual(scheduler.run_due_once(), 0)
        clock.advance(10)
        self.assertEqual(scheduler.run_due_once(), 1)
        self.assertEqual(events, ["sync"])

    def test_pause_prevents_execution(self):
        clock = FakeClock()
        events = []
        scheduler = BackgroundScheduler(clock=clock)
        scheduler.register("job", 1, lambda: events.append("job"))
        scheduler.pause()
        clock.advance(2)
        self.assertEqual(scheduler.run_due_once(), 0)
        self.assertEqual(events, [])

    def test_callback_failure_is_recorded_without_stopping_scheduler(self):
        clock = FakeClock()
        scheduler = BackgroundScheduler(clock=clock)
        scheduler.register("bad", 1, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        clock.advance(1)
        self.assertEqual(scheduler.run_due_once(), 1)
        snapshot = scheduler.snapshot()
        self.assertIn("RuntimeError", snapshot["bad"]["last_error"])
        self.assertEqual(snapshot["bad"]["run_count"], 1)

    def test_start_and_stop_thread(self):
        event = threading.Event()
        scheduler = BackgroundScheduler()
        scheduler.register("fast", 0.02, event.set, run_immediately=True)
        scheduler.start()
        self.assertTrue(event.wait(1.0))
        scheduler.stop()
        self.assertTrue(scheduler.wait(1.0))

    def test_live_scheduler_does_not_serialize_unrelated_jobs(self):
        slow_started = threading.Event()
        release_slow = threading.Event()
        fast_completed = threading.Event()

        def slow_job():
            slow_started.set()
            release_slow.wait(1.0)

        scheduler = BackgroundScheduler(max_workers=2)
        scheduler.register("slow", 60, slow_job, run_immediately=True)
        scheduler.register("fast", 60, fast_completed.set, run_immediately=True)
        scheduler.start()
        try:
            self.assertTrue(slow_started.wait(0.5))
            self.assertTrue(fast_completed.wait(0.5))
        finally:
            release_slow.set()
            scheduler.stop()
            self.assertTrue(scheduler.wait(1.0))

    def test_running_job_is_coalesced_and_never_overlaps_itself(self):
        clock = FakeClock()
        started = threading.Event()
        release = threading.Event()
        lock = threading.Lock()
        active = 0
        max_active = 0
        calls = 0

        def job():
            nonlocal active, max_active, calls
            with lock:
                active += 1
                calls += 1
                max_active = max(max_active, active)
            started.set()
            release.wait(1.0)
            with lock:
                active -= 1

        scheduler = BackgroundScheduler(clock=clock, max_workers=2)
        scheduler.register("sync", 1, job, run_immediately=True)
        self.assertEqual(scheduler.dispatch_due_once(), 1)
        self.assertTrue(started.wait(0.5))
        clock.advance(1)
        self.assertEqual(scheduler.dispatch_due_once(), 0)
        self.assertTrue(scheduler.snapshot()["sync"]["pending"])
        release.set()
        deadline = time.time() + 1.0
        while time.time() < deadline and scheduler.snapshot()["sync"]["run_count"] < 2:
            time.sleep(0.01)
        scheduler.stop()
        self.assertTrue(scheduler.wait(1.0))
        self.assertEqual(calls, 2)
        self.assertEqual(max_active, 1)
