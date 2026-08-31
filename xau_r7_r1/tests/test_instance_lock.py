from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from r7_runtime.instance_lock import SingleInstanceError, SingleInstanceLock


class SingleInstanceLockTests(unittest.TestCase):
    def test_second_lock_is_rejected_and_release_allows_reacquire(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "runtime.lock"
            first = SingleInstanceLock(path)
            second = SingleInstanceLock(path)
            first.acquire()
            try:
                with self.assertRaisesRegex(SingleInstanceError, "ANOTHER_R7_R1_INSTANCE_IS_RUNNING"):
                    second.acquire()
            finally:
                first.release()
                second.release()

            third = SingleInstanceLock(path)
            try:
                third.acquire()
            finally:
                third.release()

    def test_context_manager_releases_lock_after_exception(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "runtime.lock"
            with self.assertRaisesRegex(RuntimeError, "boom"):
                with SingleInstanceLock(path):
                    raise RuntimeError("boom")

            lock = SingleInstanceLock(path)
            try:
                lock.acquire()
            finally:
                lock.release()


if __name__ == "__main__":
    unittest.main()
