"""A process existing is insufficient: scheduler health needs a recent successful cycle."""
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deployment.scheduler import write_status
from deployment.scheduler_healthcheck import healthy, main


class SchedulerHealthTests(unittest.TestCase):
    def test_only_recent_complete_success_is_healthy(self):
        status = {"ok": True, "finished_at": 100, "results": {"run_periodic": 0, "run_kmg_operations": 0}}
        self.assertTrue(healthy(status, now=120, max_age=30))
        self.assertFalse(healthy(status, now=131, max_age=30))
        self.assertFalse(healthy(status, now=99, max_age=30))
        self.assertFalse(healthy({**status, "ok": False}, now=120, max_age=30))
        self.assertFalse(healthy({**status, "results": {"run_periodic": 0}}, now=120, max_age=30))
        self.assertFalse(healthy({**status, "results": {"run_periodic": 0, "run_kmg_operations": 124}}, now=120, max_age=30))

    def test_atomic_status_file_and_failed_cycle(self):
        with tempfile.TemporaryDirectory(prefix="kmg-scheduler-test-") as directory:
            path = Path(directory) / "status.json"
            with patch("sys.stdout", new_callable=StringIO):
                write_status(path, ok=False, results={"run_periodic": 0, "run_kmg_operations": 1}, now=100)
            self.assertFalse(path.with_suffix(".tmp").exists())
            self.assertEqual(json.loads(path.read_text())["finished_at"], 100)
            with patch.dict("os.environ", {"SCHEDULER_STATUS_PATH": str(path)}), patch("time.time", return_value=101):
                with self.assertRaises(SystemExit) as raised:
                    main()
                self.assertEqual(raised.exception.code, 1)

    def test_missing_or_corrupt_status_is_unhealthy(self):
        with tempfile.TemporaryDirectory(prefix="kmg-scheduler-test-") as directory:
            path = Path(directory) / "status.json"
            for content in (None, "broken-json", "[]"):
                if content is not None:
                    path.write_text(content)
                with patch.dict("os.environ", {"SCHEDULER_STATUS_PATH": str(path)}):
                    with self.assertRaises(SystemExit) as raised:
                        main()
                    self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
