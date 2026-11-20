"""Historial de postulaciones (SQLite local): datos de la vacante, ajuste, estado y eventos."""
from __future__ import annotations

import builtins
import csv
import io
import json
import sqlite3
import threading
from datetime import date, timedelta
from pathlib import Path

from .utils import now_iso

COLUMNS = [
    "job_id", "url", "platform", "company", "title", "country", "city", "modality", "seniority",
    "salary_text", "salary_min", "salary_max", "salary_currency", "salary_period", "salary_expectation",
    "score", "required_coverage", "skills_backed", "skills_gap",
    "status", "status_detail", "created_at", "applied_at", "updated_at", "notes", "data",
]
JSON_COLUMNS = {"skills_backed", "skills_gap", "data"}

# Flujo automático -> revisión -> proceso con la empresa.
PIPELINE_STATUSES = ["queued", "analyzing", "generating", "filling", "needs_input", "awaiting_review",
                     "submitting", "error", "skipped", "cancelled"]
PROCESS_STATUSES = ["applied", "screening", "interview", "technical", "offer", "hired", "rejected", "withdrawn"]
STATUSES = PIPELINE_STATUSES + PROCESS_STATUSES
# Hitos del proceso con la empresa (CRM): entrevistas, seguimientos, pruebas...
PROCESS_EVENT_KINDS = ("interview", "followup", "test", "offer", "other")
ADVANCED = {"screening", "interview", "technical", "offer", "hired"}

STATUS_LABELS = {
    "queued": "En cola", "analyzing": "Analizando", "generating": "Generando CV", "filling": "Completando formulario",
    "needs_input": "Necesita tu respuesta", "awaiting_review": "Listo para revisar", "submitting": "Enviando",
    "error": "Error", "skipped": "Descartada", "cancelled": "Cancelada",
    "applied": "Postulado", "screening": "En revisión RR. HH.", "interview": "Entrevista",
    "technical": "Prueba técnica", "offer": "Oferta", "hired": "Contratado", "rejected": "Rechazado",
    "withdrawn": "Retirado",
}

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS applications (
    job_id TEXT PRIMARY KEY,
    {", ".join(f"{c} {'REAL' if c in ('salary_min', 'salary_max', 'score', 'required_coverage') else 'TEXT'}"
               for c in COLUMNS[1:])}
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id);
CREATE TABLE IF NOT EXISTS process_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    due TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_process_events_job ON process_events(job_id);
"""


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------------ filas
    def _decode(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        for c in JSON_COLUMNS:
            d[c] = json.loads(d[c]) if d.get(c) else ([] if c != "data" else {})
        d["status_label"] = STATUS_LABELS.get(d.get("status") or "", d.get("status"))
        return d

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            return self._decode(self._conn.execute(
                "SELECT * FROM applications WHERE job_id=?", (job_id,)).fetchone())

    def _require(self, job_id: str) -> dict:
        row = self.get(job_id)
        if row is None:  # no debería ocurrir: se acaba de insertar o actualizar
            raise KeyError(job_id)
        return row

    def find_by_url(self, url: str) -> dict | None:
        with self._lock:
            return self._decode(self._conn.execute(
                "SELECT * FROM applications WHERE url=? ORDER BY created_at DESC", (url,)).fetchone())

    def upsert(self, job_id: str, **fields) -> dict:
        fields = {k: v for k, v in fields.items() if k in COLUMNS and k != "job_id"}
        for c in JSON_COLUMNS & fields.keys():
            fields[c] = json.dumps(fields[c], ensure_ascii=False)
        fields["updated_at"] = now_iso()
        with self._lock:
            exists = self._conn.execute("SELECT 1 FROM applications WHERE job_id=?", (job_id,)).fetchone()
            if exists:
                sets = ", ".join(f"{k}=?" for k in fields)
                self._conn.execute(f"UPDATE applications SET {sets} WHERE job_id=?", (*fields.values(), job_id))
            else:
                fields.setdefault("created_at", now_iso())
                fields.setdefault("status", "queued")
                cols = ["job_id", *fields]
                self._conn.execute(
                    f"INSERT INTO applications ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    (job_id, *fields.values()))
            self._conn.commit()
        return self._require(job_id)

    def update_data(self, job_id: str, **data) -> dict:
        """Mezcla claves en la columna JSON `data` (estado de la automatización)."""
        with self._lock:
            current = (self.get(job_id) or {}).get("data") or {}
            current.update(data)
            return self.upsert(job_id, data=current)

    def set_status(self, job_id: str, status: str, detail: str | None = None) -> dict:
        if status not in STATUSES:
            raise ValueError(f"Estado inválido '{status}'. Usa uno de: {', '.join(STATUSES)}")
        fields = {"status": status, "status_detail": detail}
        row = self.get(job_id)
        if status == "applied" and not (row or {}).get("applied_at"):
            fields["applied_at"] = now_iso()
        self.upsert(job_id, **fields)
        self.event(job_id, "status", f"{STATUS_LABELS[status]}" + (f": {detail}" if detail else ""))
        return self._require(job_id)

    def list(self, status: str | None = None, search: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM applications", []
        clauses = []
        if status:
            clauses.append("status=?")
            args.append(status)
        if search:
            clauses.append("(company LIKE ? OR title LIKE ? OR country LIKE ?)")
            args += [f"%{search}%"] * 3
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        with self._lock:
            return [row for r in self._conn.execute(sql, args).fetchall() if (row := self._decode(r)) is not None]

    def delete(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM applications WHERE job_id=?", (job_id,))
            self._conn.execute("DELETE FROM events WHERE job_id=?", (job_id,))
            self._conn.execute("DELETE FROM process_events WHERE job_id=?", (job_id,))
            self._conn.commit()

    # ------------------------------------------------------------------ eventos
    def event(self, job_id: str, kind: str, message: str) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO events (job_id, ts, kind, message) VALUES (?,?,?,?)",
                               (job_id, now_iso(), kind, message))
            self._conn.commit()

    def events(self, job_id: str) -> builtins.list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT ts, kind, message FROM events WHERE job_id=? ORDER BY id", (job_id,)).fetchall()]

    # ------------------------------------------------------------------ hitos del proceso (CRM)
    def add_process_event(self, job_id: str, kind: str, due: str, note: str = "") -> int:
        """Agenda un hito (entrevista, seguimiento...). `due` es una fecha ISO (AAAA-MM-DD, con hora opcional)."""
        if kind not in PROCESS_EVENT_KINDS:
            raise ValueError(f"Tipo inválido '{kind}'. Usa uno de: {', '.join(PROCESS_EVENT_KINDS)}")
        try:
            day = date.fromisoformat(str(due)[:10])
        except ValueError as exc:
            raise ValueError(f"Fecha inválida '{due}': usa AAAA-MM-DD.") from exc
        if not self.get(job_id):
            raise KeyError(job_id)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO process_events (job_id, kind, due, note, created_at) VALUES (?,?,?,?,?)",
                (job_id, kind, day.isoformat(), note, now_iso()))
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def process_events(self, job_id: str | None = None, pending_only: bool = False) -> builtins.list[dict]:
        sql, args = "SELECT * FROM process_events", []
        clauses = []
        if job_id:
            clauses.append("job_id=?")
            args.append(job_id)
        if pending_only:
            clauses.append("done=0")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql + " ORDER BY due, id", args).fetchall()]

    def complete_process_event(self, event_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("UPDATE process_events SET done=1 WHERE id=?", (event_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def agenda(self, days: int = 14, today: date | None = None) -> builtins.list[dict]:
        """Hitos pendientes atrasados o que vencen en los próximos `days` días, con título y empresa."""
        limit = ((today or date.today()) + timedelta(days=days)).isoformat()
        with self._lock:
            rows = self._conn.execute(
                "SELECT e.*, a.company, a.title FROM process_events e LEFT JOIN applications a ON a.job_id = e.job_id "
                "WHERE e.done=0 AND e.due <= ? ORDER BY e.due, e.id", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def count_applied_today(self, platform: str) -> int:
        today = now_iso()[:10]
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM applications WHERE platform=? AND substr(applied_at,1,10)=?",
                (platform, today)).fetchone()[0]

    # ------------------------------------------------------------------ métricas
    def stats(self) -> dict:
        rows = self.list()
        sent = [r for r in rows if r["status"] in PROCESS_STATUSES]
        advanced = [r for r in sent if r["status"] in ADVANCED]

        def avg(rs):
            vals = [r["score"] for r in rs if r.get("score") is not None]
            return round(sum(vals) / len(vals), 1) if vals else None

        def count_by(key):
            out: dict[str, int] = {}
            for r in sent:
                k = r.get(key) or "Sin dato"
                out[k] = out.get(k, 0) + 1
            return out

        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        return {
            "total": len(rows),
            "sent": len(sent),
            "by_status": by_status,
            "by_country": count_by("country"),
            "by_modality": count_by("modality"),
            "by_platform": count_by("platform"),
            "response_rate": round(100 * len(advanced) / len(sent), 1) if sent else None,
            "avg_score_advanced": avg(advanced),
            "avg_score_not_advanced": avg([r for r in sent if r["status"] not in ADVANCED]),
        }

    def export_csv(self) -> str:
        cols = [c for c in COLUMNS if c != "data"]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols + ["estado"])
        for r in self.list():
            row = []
            for c in cols:
                v = r.get(c)
                row.append(", ".join(v) if isinstance(v, list) else ("" if v is None else v))
            w.writerow(row + [r["status_label"]])
        return buf.getvalue()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
