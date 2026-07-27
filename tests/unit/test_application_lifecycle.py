from __future__ import annotations

import unittest

from runtime.services.lifecycle import ApplicationLifecycle, LifecycleState


class Resource:
    def __init__(self, events, name, wait_result=True):
        self.events = events
        self.name = name
        self.wait_result = wait_result
    def stop(self):
        self.events.append(f"stop:{self.name}")
    def wait(self, timeout):
        self.events.append(f"wait:{self.name}")
        return self.wait_result


class ApplicationLifecycleTests(unittest.TestCase):
    def test_start_background_foreground_and_shutdown(self):
        events = []
        lifecycle = ApplicationLifecycle()
        lifecycle.on_start("boot", lambda: events.append("boot"))
        lifecycle.on_background("bg", lambda: events.append("bg"))
        lifecycle.on_foreground("fg", lambda: events.append("fg"))
        lifecycle.on_shutdown("flush", lambda: events.append("flush"))
        lifecycle.register_resource("r1", Resource(events, "r1"))

        self.assertTrue(lifecycle.start().successful)
        self.assertEqual(lifecycle.state, LifecycleState.RUNNING)
        self.assertTrue(lifecycle.enter_background().successful)
        self.assertEqual(lifecycle.state, LifecycleState.BACKGROUND)
        self.assertTrue(lifecycle.enter_foreground().successful)
        report = lifecycle.shutdown()
        self.assertTrue(report.successful)
        self.assertEqual(lifecycle.state, LifecycleState.STOPPED)
        self.assertEqual(events, ["boot", "bg", "fg", "flush", "stop:r1", "wait:r1"])

    def test_shutdown_continues_after_error(self):
        events = []
        lifecycle = ApplicationLifecycle()
        lifecycle.register_resource("good", Resource(events, "good"))
        lifecycle.on_shutdown("bad", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        report = lifecycle.shutdown()
        self.assertFalse(report.successful)
        self.assertIn("stop:good", events)
        self.assertIn("wait:good", events)

    def test_wait_timeout_is_reported(self):
        lifecycle = ApplicationLifecycle()
        lifecycle.register_resource("slow", Resource([], "slow", wait_result=False))
        report = lifecycle.shutdown()
        self.assertFalse(report.successful)
        self.assertTrue(any("wait:slow" in item for item in report.errors))
