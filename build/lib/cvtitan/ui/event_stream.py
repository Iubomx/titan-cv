"""Flujo de eventos para la interfaz: se suscribe al bus de `cvtitan.telemetry` sin bloquear al motor.

El motor publica; esta clase solo encola (operación O(1)) y la interfaz drena la cola en cada refresco para medir
el ritmo de eventos y conocer el último suceso por agente.
"""
from __future__ import annotations

import queue
import time
from collections import deque

from .. import telemetry


class EventStream:
    def __init__(self, window: float = 60.0):
        self.window = window
        self._q: queue.SimpleQueue = queue.SimpleQueue()
        self._times: deque = deque()
        self.total = 0
        self.by_kind: dict[str, int] = {}
        self.last_by_agent: dict[str, str] = {}
        self._unsubscribe = None

    # ------------------------------------------------------------ ciclo de vida
    def start(self) -> "EventStream":
        if self._unsubscribe is None:
            self._unsubscribe = telemetry.subscribe(self._q.put)
        return self

    def stop(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    # ------------------------------------------------------------ consumo (hilo de la interfaz)
    def drain(self) -> int:
        """Procesa los eventos pendientes; devuelve cuántos llegaron desde el último refresco."""
        n = 0
        while True:
            try:
                ev = self._q.get_nowait()
            except queue.Empty:
                break
            n += 1
            self.total += 1
            self._times.append(ev["t"])
            self.by_kind[ev["kind"]] = self.by_kind.get(ev["kind"], 0) + 1
            if ev["kind"] == "log" and ev.get("agent"):
                self.last_by_agent[ev["agent"]] = ev.get("text", "")[:120]
        cutoff = time.time() - self.window
        while self._times and self._times[0] < cutoff:
            self._times.popleft()
        return n

    def rate_per_min(self) -> float:
        return len(self._times) * 60.0 / self.window

    def pending(self) -> int:
        return self._q.qsize()
