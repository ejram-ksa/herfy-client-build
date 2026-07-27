from __future__ import annotations

import threading
import time
import unittest
import uuid

from runtime.bootstrap.runtime.single_instance import SingleInstanceGuard


class SingleInstanceGuardTests(unittest.TestCase):
    def test_second_instance_notifies_primary(self):
        activated = threading.Event()
        app_id = f"herfy-test-instance-{uuid.uuid4().hex}"
        first = SingleInstanceGuard(app_id, on_activate=activated.set)
        second = SingleInstanceGuard(app_id)
        try:
            first_result = first.acquire()
            self.assertTrue(first_result.primary)
            second_result = second.acquire()
            self.assertFalse(second_result.primary)
            self.assertTrue(second_result.notified_existing)
            self.assertTrue(activated.wait(1.0))
        finally:
            second.close()
            first.close()

    def test_close_releases_instance_slot(self):
        app_id = f"herfy-test-release-{uuid.uuid4().hex}"
        first = SingleInstanceGuard(app_id)
        self.assertTrue(first.acquire().primary)
        first.close()
        time.sleep(0.05)
        second = SingleInstanceGuard(app_id)
        try:
            self.assertTrue(second.acquire().primary)
        finally:
            second.close()
