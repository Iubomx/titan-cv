"""Límites EXCLUSIVOS para LinkedIn (protegen la cuenta del candidato; el resto de fuentes no se ve afectado).

Configuración en config/settings.yaml -> linkedin:
  max_searches_per_run      búsquedas (páginas de resultados) por ejecución
  max_reads_per_run         avisos abiertos por ejecución
  min_seconds_between       pausa mínima entre cualquier carga de página de LinkedIn (+ azar)
  max_searches_per_day      tope diario de búsquedas (persistente entre ejecuciones)
  daily_applications        postulaciones por día (se aplica en settings.daily_limits.linkedin)
"""
from __future__ import annotations

import json
import random
import threading
import time
from datetime import date
from pathlib import Path

DEFAULTS = {"max_searches_per_run": 12, "max_reads_per_run": 30, "min_seconds_between": 20,
            "max_searches_per_day": 30, "daily_applications": 10}


def is_linkedin(url: str) -> bool:
    return "linkedin.com" in (url or "").lower()


class LinkedInGuard:
    _lock = threading.Lock()

    def __init__(self, settings: dict, state_path: Path):
        self.cfg = {**DEFAULTS, **(settings.get("linkedin") or {})}
        self.state_path = state_path
        self.searches = 0
        self.reads = 0
        self._last = 0.0

    def _day_state(self) -> dict:
        today = date.today().isoformat()
        try:
            st = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        return st if st.get("day") == today else {"day": today, "searches": 0, "reads": 0}

    def _save(self, st: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(st), encoding="utf-8")

    def exhausted(self) -> bool:
        """¿Ya no quedan búsquedas de LinkedIn permitidas (en esta ejecución o hoy)?"""
        with self._lock:
            return self.searches >= int(self.cfg["max_searches_per_run"]) or                 self._day_state()["searches"] >= int(self.cfg["max_searches_per_day"])

    def allow(self, kind: str) -> tuple[bool, str]:
        """kind: 'search' | 'read'. Si se permite, espera la pausa mínima y cuenta la petición."""
        with self._lock:
            st = self._day_state()
            if kind == "search":
                if self.searches >= int(self.cfg["max_searches_per_run"]):
                    return False, f"cap of {self.cfg['max_searches_per_run']} LinkedIn searches per run"
                if st["searches"] >= int(self.cfg["max_searches_per_day"]):
                    return False, f"daily cap of {self.cfg['max_searches_per_day']} LinkedIn searches"
            elif self.reads >= int(self.cfg["max_reads_per_run"]):
                return False, f"cap of {self.cfg['max_reads_per_run']} LinkedIn postings per run"
            wait = self._last + float(self.cfg["min_seconds_between"]) + random.uniform(2, 8) - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            if kind == "search":
                self.searches += 1
                st["searches"] += 1
            else:
                self.reads += 1
                st["reads"] = st.get("reads", 0) + 1
            self._save(st)
            return True, "ok"
