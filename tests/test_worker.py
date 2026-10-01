import os
from pathlib import Path
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import worker


class WorkerTests(unittest.TestCase):
    def test_once_processes_a_cycle_and_returns_success(self):
        cycle = Mock(return_value=([{}], [{"estado": "OK_INFERIDO"}]))
        self.assertEqual(worker.ejecutar_worker(cycle, Event(), 60, once=True), 0)
        cycle.assert_called_once_with()

    def test_review_is_not_a_worker_failure(self):
        cycle = Mock(return_value=([{}], [{"estado": "REVISAR"}]))
        self.assertEqual(worker.ejecutar_worker(cycle, Event(), 60, once=True), 0)

    def test_error_state_returns_failure_in_once_mode(self):
        cycle = Mock(return_value=([{}], [{"estado": "ERROR"}]))
        self.assertEqual(worker.ejecutar_worker(cycle, Event(), 60, once=True), 1)

    def test_network_failure_is_retried_without_logging_sensitive_message(self):
        stop = Mock()
        stop.is_set.side_effect = [False, False, True]
        cycle = Mock(side_effect=[RuntimeError("private invoice data"), ([], [])])
        with self.assertLogs(worker.LOGGER, level="INFO") as logs:
            self.assertEqual(worker.ejecutar_worker(cycle, stop, 60), 0)
        self.assertEqual(cycle.call_count, 2)
        self.assertEqual(stop.wait.call_count, 2)
        self.assertNotIn("private invoice data", "\n".join(logs.output))

    def test_stop_prevents_another_cycle(self):
        stop = Event()
        stop.set()
        cycle = Mock()
        self.assertEqual(worker.ejecutar_worker(cycle, stop, 60), 0)
        cycle.assert_not_called()

    def test_nonpositive_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            worker.ejecutar_worker(Mock(), Event(), 0)

    def test_missing_environment_is_detected_before_google_import(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertLogs(worker.LOGGER, level="ERROR"):
                self.assertEqual(worker.main(["--once"]), 2)

    def test_main_runs_once_without_starting_streamlit(self):
        cycle = Mock(return_value=([], []))
        with patch.object(worker, "validar_configuracion", return_value=60), \
                patch.object(worker.signal, "signal") as signals, \
                patch.dict("sys.modules", {"pipeline": SimpleNamespace(ejecutar_ciclo=cycle)}):
            self.assertEqual(worker.main(["--once"]), 0)
        cycle.assert_called_once_with()
        self.assertEqual(signals.call_count, 2)

    def test_startup_failure_returns_error_for_container_restart(self):
        with patch.object(worker, "validar_configuracion", return_value=60), \
                patch.object(worker.signal, "signal"), \
                patch.dict("sys.modules", {"pipeline": None}), \
                self.assertLogs(worker.LOGGER, level="ERROR"):
            self.assertEqual(worker.main(["--once"]), 1)

    def test_configuration_requires_existing_secret_and_positive_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "credential.json"
            env = {key: "test-value" for key in worker.REQUIRED_IDS}
            env.update(SERVICE_ACCOUNT_FILE=str(secret), POLL_SECONDS="60")
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(ValueError, "credenciales"):
                    worker.validar_configuracion()
                secret.write_text("{}", encoding="utf-8")
                self.assertEqual(worker.validar_configuracion(), 60)
                for invalid in ("0", "-1", "abc"):
                    with patch.dict(os.environ, {"POLL_SECONDS": invalid}):
                        with self.assertRaisesRegex(ValueError, "POLL_SECONDS"):
                            worker.validar_configuracion()


if __name__ == "__main__":
    unittest.main()
