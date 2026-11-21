"""Consumo REAL de recursos (psutil): este proceso, sus navegadores Chrome, el sistema y la red.

Muestras cacheadas por `interval` segundos para que dibujar el tablero no cueste CPU. Si psutil no está instalado,
devuelve un diccionario vacío y la interfaz muestra «—».
"""
from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path


class SystemMonitor:
    def __init__(self, interval: float = 1.0, disk_path: Path | None = None):
        self.interval = interval
        self.disk_path = disk_path
        self._lock = threading.Lock()
        self._last: dict = {}
        self._at = 0.0
        self._net = None
        try:
            import psutil
            self.psutil = psutil
            self.proc = psutil.Process(os.getpid())
            self.proc.cpu_percent(None)                  # primera llamada: inicializa el contador
            psutil.cpu_percent(None)
        except Exception:
            self.psutil = None
            self.proc = None

    def sample(self) -> dict:
        with self._lock:
            if self.psutil is None:
                return {}
            now = time.time()
            if now - self._at < self.interval and self._last:
                return self._last
            ps = self.psutil
            out: dict = {}
            try:
                children = self.proc.children(recursive=True)
                chrome = [c for c in children if _name(c).startswith("chrome")]
                out["proc_cpu"] = self.proc.cpu_percent(None)
                out["proc_mem"] = self.proc.memory_info().rss
                out["chrome_procs"] = len(chrome)
                out["chrome_mem"] = sum(_rss(c) for c in chrome)
                out["threads"] = self.proc.num_threads()
                out["sys_cpu"] = ps.cpu_percent(None)
                vm = ps.virtual_memory()
                out["sys_mem_pct"] = vm.percent
                out["sys_mem_total"] = vm.total
                net = ps.net_io_counters()
                if self._net is not None and now > self._net[0]:
                    dt = now - self._net[0]
                    out["net_down"] = max(0.0, (net.bytes_recv - self._net[1]) / dt)
                    out["net_up"] = max(0.0, (net.bytes_sent - self._net[2]) / dt)
                self._net = (now, net.bytes_recv, net.bytes_sent)
                if self.disk_path:
                    out["disk_free"] = shutil.disk_usage(self.disk_path).free
            except Exception as e:                       # nunca tumbar la interfaz por una métrica
                out["error"] = str(e)[:80]
            self._last, self._at = out, now
            return out


def _name(p) -> str:
    try:
        return p.name().lower()
    except Exception:
        return ""


def _rss(p) -> int:
    try:
        return p.memory_info().rss
    except Exception:
        return 0


def human_bytes(n: float | None) -> str:
    if n is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:,.0f} {unit}" if unit in ("B", "KB") else f"{n:,.1f} {unit}"
        n /= 1024
    return "—"
