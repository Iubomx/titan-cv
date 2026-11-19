"""Infraestructura de procesamiento continuo: cola persistente, límites por dominio y cortacircuitos.

- TaskQueue: tareas idempotentes por `key` (p. ej. "discover:remotive:2026-11-17"). Si el proceso se reinicia,
  las tareas `done` no se repiten y las `running` vencidas vuelven a `pending` (reanudación).
- CircuitBreaker: si una fuente falla N veces seguidas, se «abre» por un tiempo (no se insiste contra un portal
  caído); se cierra sola tras el enfriamiento. Estado persistente.
- DomainLimiter: intervalo mínimo entre consultas al mismo dominio (cortesía con cada proveedor).
- run_parallel: ejecuta conectores independientes en paralelo con todo lo anterior.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from .utils import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    key TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT, status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT, started_at TEXT, finished_at TEXT, last_error TEXT, result TEXT
);
CREATE TABLE IF NOT EXISTS source_health (
    source TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0, open_until TEXT, last_ok TEXT, last_error TEXT
);
"""


class _LockedConn:
    """Conexión SQLite compartida entre hilos: cada operación se serializa con un candado."""

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn
        self._lock = threading.RLock()

    def execute(self, sql, args=()):
        with self._lock:
            cur = self._c.execute(sql, args)
            rows = cur.fetchall() if cur.description else None
            return _Result(rows, cur.rowcount)

    def executescript(self, sql):
        with self._lock:
            return self._c.executescript(sql)


class _Result:
    def __init__(self, rows, rowcount):
        self._rows, self.rowcount = rows or [], rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


def _conn(path: Path) -> "_LockedConn":
    c = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    c.executescript(SCHEMA)
    return _LockedConn(c)


def _ts(delta_s: float = 0) -> str:
    return (datetime.now() + timedelta(seconds=delta_s)).replace(microsecond=0).isoformat()


class TaskQueue:
    def __init__(self, path: Path, stale_minutes: int = 60):
        self.c = _conn(path)
        self._lock = threading.RLock()
        # Reanudación: lo que quedó «running» de una ejecución caída vuelve a la cola.
        self.c.execute("UPDATE tasks SET status='pending' WHERE status='running' AND started_at < ?",
                       (_ts(-stale_minutes * 60),))

    def add(self, key: str, kind: str, payload: dict | None = None) -> bool:
        with self._lock:
            cur = self.c.execute("INSERT OR IGNORE INTO tasks(key, kind, payload) VALUES (?,?,?)",
                                 (key, kind, json.dumps(payload or {}, ensure_ascii=False)))
            return cur.rowcount == 1

    def claim(self, key: str) -> bool:
        with self._lock:
            cur = self.c.execute("UPDATE tasks SET status='running', started_at=?, attempts=attempts+1 "
                                 "WHERE key=? AND status IN ('pending','retry') AND (next_at IS NULL OR next_at<=?)",
                                 (now_iso(), key, now_iso()))
            return cur.rowcount == 1

    def done(self, key: str, result: dict | None = None) -> None:
        with self._lock:
            self.c.execute("UPDATE tasks SET status='done', finished_at=?, result=? WHERE key=?",
                           (now_iso(), json.dumps(result or {}, ensure_ascii=False, default=str), key))

    def fail(self, key: str, error: str, max_attempts: int = 4) -> None:
        with self._lock:
            row = self.c.execute("SELECT attempts FROM tasks WHERE key=?", (key,)).fetchone()
            n = row["attempts"] if row else 1
            if n >= max_attempts:
                self.c.execute("UPDATE tasks SET status='failed', last_error=?, finished_at=? WHERE key=?",
                               (error[:500], now_iso(), key))
            else:                                          # backoff exponencial: 2, 4, 8 minutos…
                self.c.execute("UPDATE tasks SET status='retry', last_error=?, next_at=? WHERE key=?",
                               (error[:500], _ts(60 * 2 ** n), key))

    def status(self, key: str) -> str | None:
        r = self.c.execute("SELECT status FROM tasks WHERE key=?", (key,)).fetchone()
        return r["status"] if r else None

    def result(self, key: str) -> dict:
        r = self.c.execute("SELECT result FROM tasks WHERE key=?", (key,)).fetchone()
        return json.loads(r["result"]) if r and r["result"] else {}

    def counts(self) -> dict:
        return {r["status"]: r["n"] for r in self.c.execute("SELECT status, COUNT(*) n FROM tasks GROUP BY status")}


class CircuitBreaker:
    def __init__(self, path: Path, threshold: int = 3, cooldown_minutes: int = 60):
        self.c = _conn(path)
        self.threshold, self.cooldown = threshold, cooldown_minutes
        self._lock = threading.RLock()

    def allow(self, source: str) -> bool:
        r = self.c.execute("SELECT open_until FROM source_health WHERE source=?", (source,)).fetchone()
        return not (r and r["open_until"] and r["open_until"] > now_iso())

    def ok(self, source: str) -> None:
        with self._lock:
            self.c.execute("INSERT INTO source_health(source, failures, last_ok) VALUES (?,0,?) "
                           "ON CONFLICT(source) DO UPDATE SET failures=0, open_until=NULL, last_ok=excluded.last_ok",
                           (source, now_iso()))

    def failure(self, source: str, error: str) -> bool:
        """Registra un fallo; True si el circuito quedó abierto."""
        with self._lock:
            self.c.execute("INSERT INTO source_health(source, failures, last_error) VALUES (?,1,?) "
                           "ON CONFLICT(source) DO UPDATE SET failures=failures+1, last_error=excluded.last_error",
                           (source, error[:300]))
            n = self.c.execute("SELECT failures FROM source_health WHERE source=?", (source,)).fetchone()["failures"]
            if n >= self.threshold:
                self.c.execute("UPDATE source_health SET open_until=? WHERE source=?", (_ts(self.cooldown * 60), source))
                return True
            return False

    def report(self) -> list[dict]:
        return [dict(r) for r in self.c.execute("SELECT * FROM source_health ORDER BY source")]


class DomainLimiter:
    """Intervalo mínimo entre llamadas al mismo dominio (en este proceso)."""

    def __init__(self, min_interval_s: float = 2.0):
        self.min = min_interval_s
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url_or_domain: str) -> None:
        d = urlparse(url_or_domain).hostname or url_or_domain
        with self._lock:
            delay = self._last.get(d, 0) + self.min - time.monotonic()
            self._last[d] = time.monotonic() + max(0.0, delay)
        if delay > 0:
            time.sleep(delay)


def run_parallel(jobs: dict, db_path: Path, day_key: str, workers: int = 6, say=print) -> dict:
    """jobs = {nombre: función_sin_argumentos -> list}. Devuelve {nombre: resultado | 'error: …' | 'omitida: …'}.
    Cada conector es una tarea idempotente del día (si ya se hizo hoy, se reutiliza su caché)."""
    q, cb = TaskQueue(db_path), CircuitBreaker(db_path)
    out: dict = {}

    def one(name, fn):
        key = f"discover:{name}:{day_key}"
        q.add(key, "discover", {"source": name})
        if not cb.allow(name):
            return name, "skipped: circuit open (source failing; retrying later)"
        if q.status(key) != "done" and not q.claim(key):
            return name, f"skipped: task {q.status(key)}"
        try:
            res = fn()
            q.done(key, {"count": len(res)})
            cb.ok(name)
            return name, res
        except Exception as e:                         # una fuente caída no detiene las demás
            q.fail(key, f"{type(e).__name__}: {e}")
            opened = cb.failure(name, f"{type(e).__name__}: {e}")
            return name, f"error: {type(e).__name__}" + (" (circuit open)" if opened else "")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, n, f) for n, f in jobs.items()]
        for fut in as_completed(futures):
            name, res = fut.result()
            out[name] = res
    return out
