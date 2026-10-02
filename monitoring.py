"""Estado de solo consulta del worker, compartido mediante archivos atómicos.

Sin MONITOR_DIR no hace nada: Render y las pruebas conservan su comportamiento.
Los errores del monitoreo no interrumpen una factura ni cambian Google Sheets.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock, Thread

LOGGER = logging.getLogger("facturas.monitoring")
LOCK = RLock()


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, data):
    """Reemplazo atómico: el navegador nunca recibe medio documento JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False) as handle:
            temporary = handle.name
            json.dump(data, handle, ensure_ascii=False, allow_nan=False)
        # El panel solo necesita leer estos archivos; su volumen es read-only.
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def publish(kind, **values):
    directory = os.getenv("MONITOR_DIR")
    if not directory:
        return
    try:
        with LOCK:
            path = Path(directory) / "state.json"
            state = read_json(path, {})
            if kind == "heartbeat":
                state.update(values, heartbeat_at=now())
            elif kind == "stage":
                current = state.get("current") or {}
                current.update(values, stage_at=now())
                state.update(current=current, status="processing")
            elif kind == "file_start":
                state.update(status="processing", current={**values, "started_at": now(),
                                                          "stage": "Descargando"})
            elif kind == "queue":
                state.update(queue=values["files"], cycle_started_at=now(), status="checking")
            elif kind == "result":
                state["queue"] = [item for item in state.get("queue", [])
                                  if item["id"] != values.get("drive_id")]
                state.update(current=None)
            elif kind == "cycle_end":
                state.update(status="idle", current=None, last_cycle_at=now(),
                             last_cycle_error=None, **values)
            elif kind == "cycle_error":
                state.update(status="error", current=None, last_cycle_error=values["error"])
            elif kind == "start":
                state.update(status="starting", current=None, queue=[], started_at=now(),
                             last_cycle_error=None, **values)
            elif kind == "stop":
                state.update(status="stopped", current=None)
            if kind not in {"heartbeat", "stage", "queue"}:
                events = state.get("events", [])
                events.append({"kind": kind, "at": now(), **values})
                state["events"] = events[-200:]
            write_json(path, state)
    except Exception as exc:  # noqa: BLE001 - fallas del panel no deben detener una factura
        LOGGER.warning("No se pudo publicar el monitoreo (%s)", type(exc).__name__)


def sync_records(records):
    directory = os.getenv("MONITOR_DIR")
    if directory:
        try:
            write_json(Path(directory) / "invoices.json", {"synced_at": now(), "records": records})
            publish("heartbeat", history_error=None)
        except Exception as exc:  # noqa: BLE001 - preservar la última copia ante cualquier fallo
            publish("heartbeat", history_error=type(exc).__name__)


class ResourceSampler:
    """Métricas de la VM y cgroup del worker, sin Docker socket ni privilegios."""

    def __init__(self, proc="/proc", cgroup="/sys/fs/cgroup", disk="/"):
        self.proc, self.cgroup, self.disk = Path(proc), Path(cgroup), Path(disk)
        self.previous = None

    def sample(self):
        cpu = [int(value) for value in (self.proc / "stat").read_text().splitlines()[0].split()[1:9]]
        total, idle = sum(cpu), cpu[3] + cpu[4]
        clock = time.monotonic()
        cpu_usage = int((self.cgroup / "cpu.stat").read_text().split("usage_usec ")[1].split()[0])
        host_cpu = worker_cpu = None
        if self.previous:
            prev_total, prev_idle, prev_usage, prev_clock = self.previous
            delta = total - prev_total
            host_cpu = round(max(0, min(100, 100 * (1 - (idle - prev_idle) / delta))), 1) if delta else 0
            worker_cpu = round(max(0, (cpu_usage - prev_usage) / (clock - prev_clock) / 10000), 1)
        self.previous = total, idle, cpu_usage, clock
        memory = {line.split(":")[0]: int(line.split()[1]) * 1024
                  for line in (self.proc / "meminfo").read_text().splitlines()
                  if line.startswith(("MemTotal:", "MemAvailable:", "SwapTotal:", "SwapFree:"))}
        disk = os.statvfs(self.disk)
        maximum = (self.cgroup / "memory.max").read_text().strip()
        return {
            "cpu_percent": host_cpu, "worker_cpu_percent": worker_cpu,
            "cpu_count": os.cpu_count(), "load": list(os.getloadavg()),
            "memory_total": memory["MemTotal"], "memory_available": memory["MemAvailable"],
            "memory_used": memory["MemTotal"] - memory["MemAvailable"],
            "swap_total": memory.get("SwapTotal", 0),
            "swap_used": memory.get("SwapTotal", 0) - memory.get("SwapFree", 0),
            "worker_memory": int((self.cgroup / "memory.current").read_text()),
            "worker_memory_limit": None if maximum == "max" else int(maximum),
            "disk_total": disk.f_blocks * disk.f_frsize,
            "disk_available": disk.f_bavail * disk.f_frsize,
            "uptime_seconds": float((self.proc / "uptime").read_text().split()[0]),
        }


def start_monitor(stop):
    if not os.getenv("MONITOR_DIR"):
        return None
    sampler = ResourceSampler(disk=os.getenv("MONITOR_DIR"))

    def heartbeat():
        while not stop.is_set():
            try:
                publish("heartbeat", metrics=sampler.sample(), metrics_error=None)
            except Exception as exc:  # noqa: BLE001 - conservar heartbeat aunque falle una métrica
                publish("heartbeat", metrics_error=type(exc).__name__)
            stop.wait(5)

    thread = Thread(target=heartbeat, name="monitor-heartbeat", daemon=True)
    thread.start()
    return thread
