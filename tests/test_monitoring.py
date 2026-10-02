import json
import os
import tempfile
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import monitoring


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        env = patch.dict(os.environ, {"MONITOR_DIR": self.directory.name})
        env.start()
        self.addCleanup(env.stop)

    def state(self):
        return monitoring.read_json(self.root / "state.json", {})

    def test_progress_and_results_preserve_heartbeat_and_queue(self):
        monitoring.publish("start", interval=60)
        monitoring.publish("heartbeat", metrics={"cpu_percent": 50})
        monitoring.publish("queue", files=[{"id": "a"}, {"id": "b"}])
        monitoring.publish("file_start", drive_id="a", archivo="a.pdf")
        started = self.state()["current"]["started_at"]
        monitoring.publish("stage", stage="Leyendo PDF / OCR")
        self.assertEqual(self.state()["current"]["started_at"], started)
        self.assertEqual(self.state()["current"]["stage"], "Leyendo PDF / OCR")
        monitoring.publish("result", drive_id="a", estado="REVISAR")
        self.assertEqual(self.state()["queue"], [{"id": "b"}])
        self.assertIsNone(self.state()["current"])
        self.assertEqual(self.state()["metrics"]["cpu_percent"], 50)
        monitoring.publish("cycle_error", error="TimeoutError")
        self.assertEqual(self.state()["status"], "error")
        monitoring.publish("cycle_end", counts={"REVISAR": 1}, detected=1)
        self.assertEqual(self.state()["status"], "idle")
        self.assertIsNone(self.state()["last_cycle_error"])
        monitoring.publish("stop")
        self.assertEqual(self.state()["status"], "stopped")

    def test_events_are_bounded_and_persist_across_restart(self):
        for i in range(210):
            monitoring.publish("result", estado="OK", drive_id=str(i))
        self.assertEqual(len(self.state()["events"]), 200)
        monitoring.publish("start", interval=60)
        self.assertEqual(len(self.state()["events"]), 200)
        self.assertEqual(self.state()["events"][-2]["drive_id"], "209")

    def test_history_sync_and_write_failure_do_not_break_processing(self):
        monitoring.sync_records([{"archivo": "a.pdf", "estado": "OK"}])
        data = monitoring.read_json(self.root / "invoices.json")
        self.assertEqual(data["records"][0]["archivo"], "a.pdf")
        with patch.object(monitoring, "write_json", side_effect=PermissionError), \
                self.assertLogs(monitoring.LOGGER, level="WARNING"):
            monitoring.sync_records([])
        self.assertEqual(monitoring.read_json(self.root / "invoices.json"), data)

    def test_no_monitor_dir_keeps_existing_worker_unchanged(self):
        with patch.dict(os.environ, {"MONITOR_DIR": ""}):
            monitoring.publish("start")
            monitoring.sync_records([])
            self.assertIsNone(monitoring.start_monitor(Event()))
        self.assertFalse((self.root / "state.json").exists())

    def test_partial_json_and_missing_files_are_ignored(self):
        self.assertEqual(monitoring.read_json(self.root / "missing", []), [])
        (self.root / "state.json").write_text("{", encoding="utf-8")
        monitoring.publish("start", interval=60)
        self.assertEqual(self.state()["interval"], 60)

    def test_resource_sampler_uses_cpu_deltas_and_available_memory(self):
        proc, cgroup = self.root / "proc", self.root / "cgroup"
        proc.mkdir()
        cgroup.mkdir()
        (proc / "stat").write_text("cpu 10 0 10 80 0 0 0 0\n", encoding="utf-8")
        (proc / "meminfo").write_text("MemTotal: 1000 kB\nMemAvailable: 400 kB\nSwapTotal: 100 kB\nSwapFree: 80 kB\n", encoding="utf-8")
        (proc / "uptime").write_text("1234.5 2000.0\n", encoding="utf-8")
        (cgroup / "cpu.stat").write_text("usage_usec 1000000\n", encoding="utf-8")
        (cgroup / "memory.current").write_text("1024", encoding="utf-8")
        (cgroup / "memory.max").write_text("4096", encoding="utf-8")
        disk = SimpleNamespace(f_blocks=100, f_bavail=40, f_frsize=1024)
        with patch.object(monitoring.os, "statvfs", return_value=disk, create=True), \
                patch.object(monitoring.os, "getloadavg", return_value=(1, 2, 3), create=True), \
                patch.object(monitoring.time, "monotonic", side_effect=[1, 2, 3]):
            sampler = monitoring.ResourceSampler(proc, cgroup, self.root)
            first = sampler.sample()
            self.assertIsNone(first["cpu_percent"])
            self.assertEqual(first["memory_used"], 600 * 1024)
            self.assertEqual(first["swap_used"], 20 * 1024)
            (proc / "stat").write_text("cpu 20 0 20 160 0 0 0 0\n", encoding="utf-8")
            (cgroup / "cpu.stat").write_text("usage_usec 1500000\n", encoding="utf-8")
            second = sampler.sample()
            self.assertEqual(second["cpu_percent"], 20)
            self.assertEqual(second["worker_cpu_percent"], 50)
            self.assertEqual(second["disk_available"], 40 * 1024)
            (cgroup / "memory.max").write_text("max", encoding="utf-8")
            self.assertIsNone(sampler.sample()["worker_memory_limit"])

    def test_heartbeat_reports_collection_failure_and_stops(self):
        stop = Event()
        def fail():
            stop.set()
            raise OSError("private details")
        with patch.object(monitoring.ResourceSampler, "sample", side_effect=fail):
            thread = monitoring.start_monitor(stop)
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.state()["metrics_error"], "OSError")
        self.assertNotIn("private details", json.dumps(self.state()))

    def test_heartbeat_publishes_success(self):
        stop = Event()
        def sample():
            stop.set()
            return {"cpu_percent": 25}
        with patch.object(monitoring.ResourceSampler, "sample", side_effect=sample):
            monitoring.start_monitor(stop).join(2)
        self.assertEqual(self.state()["metrics"]["cpu_percent"], 25)


if __name__ == "__main__":
    unittest.main()
