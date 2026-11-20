"""Registro global y permanente de vacantes: deduplicación entre portales e idempotencia de envíos.

REGLA CRÍTICA: una vacante con envío confirmado (SUBMITTED_CONFIRMED) nunca se vuelve a enviar.

Identidad de una vacante (`logical_key`), en orden de prioridad:
  1. ID oficial del ATS de la empresa (Greenhouse, Lever, Workday, SuccessFactors, Get on Board, Computrabajo…).
  2. ID de requisición publicado en el aviso + identidad del empleador.
  3. Huella normalizada empleador + cargo + ubicación (mecanismo secundario).
Una misma vacante vista en varios portales queda UNA sola vez, con todas sus URLs en `vacancy_sources`.
Una nueva requisición del mismo empleador (otro ID) es una vacante distinta aunque el cargo sea idéntico.

Concurrencia: `claim()` es un UPDATE condicional atómico (SQLite en modo WAL, busy_timeout), de modo que dos
workers o procesos no pueden enviar la misma vacante. Todo persiste en data/cvtitan.db (se mantiene tras reinicios).
Preparado para PostgreSQL: SQL estándar, claves explícitas, sin tipos propios de SQLite salvo AUTOINCREMENT.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .utils import normalize, now_iso

STATES = ["DISCOVERED", "QUALIFIED", "QUEUED", "IN_PROGRESS", "SUBMITTED_CONFIRMED", "SUBMISSION_UNKNOWN",
          "PENDING_REVIEW", "FAILED", "REJECTED", "CLOSED"]
# Estados desde los que un worker puede tomar la vacante para enviarla.
CLAIMABLE = ("DISCOVERED", "QUALIFIED", "QUEUED", "FAILED")
# Estados que bloquean cualquier envío automático.
BLOCKING = ("SUBMITTED_CONFIRMED", "SUBMISSION_UNKNOWN", "IN_PROGRESS", "PENDING_REVIEW", "CLOSED")
LOCK_MINUTES = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS employers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    norm_name TEXT NOT NULL UNIQUE,
    display_name TEXT,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vacancies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logical_key TEXT NOT NULL UNIQUE,
    key_kind TEXT NOT NULL,                 -- ats | requisition | fingerprint
    fingerprint TEXT NOT NULL,
    employer_id INTEGER REFERENCES employers(id),
    company TEXT, title TEXT, country TEXT, city TEXT, modality TEXT,
    canonical_url TEXT, ats TEXT, ats_job_id TEXT, requisition_id TEXT,
    source TEXT, published_at TEXT, detected_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DISCOVERED',
    status_at TEXT NOT NULL,
    lock_owner TEXT, lock_at TEXT,
    submitted_at TEXT, confirmation TEXT,
    job_id TEXT,                            -- vínculo con applications (historial/CV)
    data TEXT
);
CREATE INDEX IF NOT EXISTS idx_vac_fp ON vacancies(fingerprint);
CREATE INDEX IF NOT EXISTS idx_vac_status ON vacancies(status);
CREATE TABLE IF NOT EXISTS vacancy_sources (
    url TEXT PRIMARY KEY,
    vacancy_id INTEGER NOT NULL REFERENCES vacancies(id),
    source TEXT, seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_id INTEGER NOT NULL REFERENCES vacancies(id),
    worker TEXT, started_at TEXT NOT NULL, finished_at TEXT,
    submit_clicked INTEGER DEFAULT 0, outcome TEXT, detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_att_vac ON attempts(vacancy_id);
"""

# ---------------------------------------------------------------- normalización
CORP = r"\b(inc|incorporated|llc|ltd|limited|gmbh|ag|s\.?a\.?s?|spa|s\.?p\.?a\.?|corp|corporation|co|company|plc|" \
       r"srl|ltda|limitada|bv|oy|ab|as|pty|group|grupo|holding)\b\.?"


def norm_company(name: str | None) -> str:
    n = normalize(name or "")
    n = re.sub(r"\(.*?\)|\bvia\b.*$|\bvía\b.*$", " ", n)
    n = re.sub(CORP, " ", n)
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def norm_title(title: str | None) -> str:
    t = normalize(title or "")
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", t)
    t = re.sub(r"\b(remote|remoto|hybrid|hibrido|latam|worldwide|full[- ]?time|part[- ]?time|contract)\b", " ", t)
    t = re.sub(r"\s[-|–—]\s.*$", " ", t)             # "Cargo - Ciudad" / "Cargo | Empresa"
    t = re.sub(r"\b(sr|snr)\b\.?", "senior", t)
    t = re.sub(r"\b(jr)\b\.?", "junior", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def norm_place(country: str | None, city: str | None, modality: str | None) -> str:
    if normalize(modality or "") == "remoto":
        return "remoto"
    return re.sub(r"[^a-z0-9]+", " ", normalize(f"{country or ''} {city or ''}")).strip()


def fingerprint(company: str | None, title: str | None, country=None, city=None, modality=None) -> str:
    raw = f"{norm_company(company)}|{norm_title(title)}|{norm_place(country, city, modality)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


ATS_PATTERNS = [
    ("greenhouse", r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)|[?&]gh_jid=(\d+)"),
    ("lever", r"jobs\.lever\.co/([\w.-]+)/([0-9a-f-]{36})"),
    ("ashby", r"jobs\.ashbyhq\.com/([\w.-]+)/([0-9a-f-]{36})"),
    ("workday", r"([\w-]+)\.wd\d+\.myworkdayjobs\.com/.*?/job/.*?_([A-Z]*-?\d[\w-]*)$"),
    ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)/(\d+)"),
    ("successfactors", r"(?:https?://)([\w.-]+)/job/[^/]+/(\d+)"),
    ("linkedin", r"linkedin\.com/jobs/view/(\d+)"),
    ("indeed", r"indeed\.com/viewjob\?(?:.*&)?jk=([0-9a-f]+)"),
    ("getonboard", r"getonbrd\.com/jobs/[^/]+/([^/?#]+)"),
    ("computrabajo", r"computrabajo\.com/ofertas-de-trabajo/oferta-de-trabajo-.*-([0-9A-F]{32})"),
    ("chiletrabajos", r"chiletrabajos\.cl/trabajo/.*-(\d+)$"),
]
REQUISITION = re.compile(r"(?i)(?:req(?:uisition)?\.?\s*(?:id|#|no\.?|number)?|job\s*(?:id|#|code)|"
                         r"c[oó]digo(?: de)? (?:aviso|oferta|cargo)|id (?:de )?(?:la )?oferta)\s*[:#]?\s*([A-Z0-9][\w-]{2,24})")


def canonical_url(url: str) -> str:
    u = urlparse(url.strip())
    q = parse_qs(u.query)
    keep = {k: v for k, v in q.items() if k in ("jk", "gh_jid", "for", "id", "jobId")}
    query = "&".join(f"{k}={v[0]}" for k, v in sorted(keep.items()))
    path = re.sub(r"/+$", "", u.path)
    return f"{u.scheme}://{(u.hostname or '').lower().removeprefix('www.')}{path}" + (f"?{query}" if query else "")


def ats_identity(url: str) -> tuple[str, str] | None:
    """(ats, id_estable) si la URL identifica una vacante concreta en un sistema conocido."""
    for ats, rx in ATS_PATTERNS:
        m = re.search(rx, url)
        if m:
            ident = ":".join(g for g in m.groups() if g)
            return ats, ident
    return None


def requisition_id(text: str | None) -> str | None:
    m = REQUISITION.search(text or "")
    return m.group(1).upper() if m else None


# ---------------------------------------------------------------- registro
class Registry:
    def __init__(self, path: Path, worker: str = "main"):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.worker = worker
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.executescript(SCHEMA)

    def close(self):
        self._conn.close()

    # -------------------------------------------------- utilidades
    def _q(self, sql: str, args=()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def get(self, vid: int) -> dict | None:
        r = self._q("SELECT * FROM vacancies WHERE id=?", (vid,))
        return r[0] if r else None

    def by_url(self, url: str) -> dict | None:
        r = self._q("SELECT v.* FROM vacancy_sources s JOIN vacancies v ON v.id=s.vacancy_id WHERE s.url=?",
                    (canonical_url(url),))
        return r[0] if r else None

    def _require(self, vid: int | None) -> dict:
        row = self.get(vid) if vid is not None else None
        if row is None:  # no debería ocurrir: la vacante se acaba de crear o actualizar
            raise KeyError(vid)
        return row

    def sources(self, vid: int) -> list[str]:
        return [r["url"] for r in self._q("SELECT url FROM vacancy_sources WHERE vacancy_id=?", (vid,))]

    def _employer(self, company: str | None) -> int | None:
        n = norm_company(company)
        if not n:
            return None
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO employers(norm_name, display_name, first_seen) VALUES (?,?,?)",
                               (n, company, now_iso()))
            return self._conn.execute("SELECT id FROM employers WHERE norm_name=?", (n,)).fetchone()[0]

    # -------------------------------------------------- alta / fusión
    def register(self, url: str, company: str | None = None, title: str | None = None, country: str | None = None,
                 city: str | None = None, modality: str | None = None, source: str | None = None,
                 text: str | None = None, published_at: str | None = None, status: str = "DISCOVERED",
                 job_id: str | None = None) -> dict:
        """Registra (o reconoce) una vacante y devuelve su fila. Idempotente: llamarla N veces no duplica."""
        curl = canonical_url(url)
        fp = fingerprint(company, title, country, city, modality)
        ats = ats_identity(url)
        req = requisition_id(text)
        emp = self._employer(company)
        if ats and ats[0] not in ("linkedin", "indeed"):        # ID del ATS del empleador o de la bolsa
            key, kind = f"{ats[0]}:{ats[1]}", "ats"
        elif req and emp:
            key, kind = f"req:{emp}:{req}", "requisition"
        else:
            key, kind = f"fp:{fp}", "fingerprint"
        now = now_iso()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT v.* FROM vacancy_sources s JOIN vacancies v ON v.id=s.vacancy_id WHERE s.url=?",
                    (curl,)).fetchone()
                if row is None:
                    row = self._conn.execute("SELECT * FROM vacancies WHERE logical_key=?", (key,)).fetchone()
                if row is None and title and company:
                    # Mecanismo secundario: misma huella (empleador+cargo+lugar). No se fusiona si ambas tienen
                    # requisición/ATS DISTINTOS (regla: nueva requisición = vacante distinta).
                    for cand in self._conn.execute("SELECT * FROM vacancies WHERE fingerprint=?", (fp,)).fetchall():
                        if kind == "fingerprint" or cand["key_kind"] == "fingerprint":
                            row = cand
                            break
                if row is None:
                    cur = self._conn.execute(
                        "INSERT INTO vacancies(logical_key, key_kind, fingerprint, employer_id, company, title, country,"
                        " city, modality, canonical_url, ats, ats_job_id, requisition_id, source, published_at,"
                        " detected_at, status, status_at, job_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (key, kind, fp, emp, company, title, country, city, modality, curl,
                         ats[0] if ats else None, ats[1] if ats else None, req, source, published_at, now,
                         status, now, job_id))
                    vid = cur.lastrowid
                else:
                    vid = row["id"]
                    # Si ahora conocemos una identidad más fuerte, se completa (sin cambiar el estado).
                    if kind != "fingerprint" and row["key_kind"] == "fingerprint":
                        clash = self._conn.execute("SELECT id FROM vacancies WHERE logical_key=?", (key,)).fetchone()
                        if clash is None:
                            self._conn.execute("UPDATE vacancies SET logical_key=?, key_kind=?, ats=?, ats_job_id=?,"
                                               " requisition_id=COALESCE(requisition_id, ?) WHERE id=?",
                                               (key, kind, ats[0] if ats else None, ats[1] if ats else None, req, vid))
                    if job_id and not row["job_id"]:
                        self._conn.execute("UPDATE vacancies SET job_id=? WHERE id=?", (job_id, vid))
                self._conn.execute("INSERT OR IGNORE INTO vacancy_sources(url, vacancy_id, source, seen_at)"
                                   " VALUES (?,?,?,?)", (curl, vid, source, now))
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return self._require(vid)

    # -------------------------------------------------- reglas de envío
    def can_submit(self, vid: int) -> tuple[bool, str]:
        v = self.get(vid)
        if v is None:
            return False, "unknown job"
        if v["status"] == "SUBMITTED_CONFIRMED":
            return False, f"already sent and confirmed ({v['submitted_at'] or ''})"
        if v["status"] == "SUBMISSION_UNKNOWN":
            return False, "submission outcome unknown: verify before retrying"
        if v["status"] == "PENDING_REVIEW":
            return False, "awaiting human review"
        if v["status"] == "CLOSED":
            return False, "job closed or discarded"
        if v["status"] == "IN_PROGRESS" and not self._lock_expired(v):
            return False, f"in progress by {v['lock_owner']}"
        # Otra vacante con la MISMA huella ya confirmada (p. ej. otra URL sin ATS común): no reenviar.
        # Solo es «gemela» si al menos una de las dos no tiene identidad oficial (ATS o requisición): dos IDs
        # oficiales distintos son vacantes distintas (regla 5).
        twin = self._q("SELECT id FROM vacancies WHERE fingerprint=? AND id<>? AND status='SUBMITTED_CONFIRMED'"
                       " AND (key_kind='fingerprint' OR ?='fingerprint')",
                       (v["fingerprint"], vid, v["key_kind"]))
        if twin:
            return False, f"duplicate of job #{twin[0]['id']}, already sent"
        return True, "ok"

    @staticmethod
    def _lock_expired(v: dict) -> bool:
        from datetime import datetime, timedelta
        try:
            return datetime.fromisoformat(v["lock_at"]) < datetime.now() - timedelta(minutes=LOCK_MINUTES)
        except (TypeError, ValueError):
            return True

    def claim(self, vid: int, worker: str | None = None) -> bool:
        """Toma la vacante para enviarla. Atómico: solo un worker/proceso puede ganar."""
        ok, _ = self.can_submit(vid)
        if not ok:
            return False
        from datetime import datetime, timedelta
        worker = worker or self.worker
        now = now_iso()
        cutoff = (datetime.now() - timedelta(minutes=LOCK_MINUTES)).replace(microsecond=0).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE vacancies SET status='IN_PROGRESS', lock_owner=?, lock_at=?, status_at=? "
                "WHERE id=? AND (status IN (%s) OR (status='IN_PROGRESS' AND lock_at < ?))"
                % ",".join("?" * len(CLAIMABLE)),
                (worker, now, now, vid, *CLAIMABLE, cutoff))
            if cur.rowcount != 1:
                return False
            self._conn.execute("INSERT INTO attempts(vacancy_id, worker, started_at) VALUES (?,?,?)", (vid, worker, now))
            return True

    def _attempt(self, vid: int) -> int | None:
        r = self._q("SELECT id FROM attempts WHERE vacancy_id=? AND finished_at IS NULL ORDER BY id DESC LIMIT 1",
                    (vid,))
        return r[0]["id"] if r else None

    def mark_clicked(self, vid: int) -> None:
        """Se llama JUSTO antes de pulsar «Enviar»: si después falla algo, el resultado pasa a desconocido."""
        aid = self._attempt(vid)
        if aid:
            with self._lock:
                self._conn.execute("UPDATE attempts SET submit_clicked=1 WHERE id=?", (aid,))

    def finish(self, vid: int, outcome: str, detail: str = "", confirmation: str | None = None) -> dict:
        """outcome: confirmed | failed | pending_review | rejected | closed | unknown | released."""
        aid = self._attempt(vid)
        clicked = bool(aid and self._q("SELECT submit_clicked FROM attempts WHERE id=?", (aid,))[0]["submit_clicked"])
        if outcome == "failed" and clicked:
            outcome = "unknown"                    # hubo clic en Enviar: no se sabe si llegó -> no reintentar
        status = {"confirmed": "SUBMITTED_CONFIRMED", "failed": "FAILED", "pending_review": "PENDING_REVIEW",
                  "rejected": "REJECTED", "closed": "CLOSED", "unknown": "SUBMISSION_UNKNOWN",
                  "released": "QUALIFIED"}[outcome]
        now = now_iso()
        with self._lock:
            self._conn.execute(
                "UPDATE vacancies SET status=?, status_at=?, lock_owner=NULL, lock_at=NULL,"
                " submitted_at=CASE WHEN ?='SUBMITTED_CONFIRMED' THEN ? ELSE submitted_at END,"
                " confirmation=COALESCE(?, confirmation) WHERE id=?",
                (status, now, status, now, confirmation, vid))
            if aid:
                self._conn.execute("UPDATE attempts SET finished_at=?, outcome=?, detail=? WHERE id=?",
                                   (now, status, detail[:500], aid))
        return self._require(vid)

    def set_status(self, vid: int, status: str) -> None:
        assert status in STATES, status
        with self._lock:
            self._conn.execute("UPDATE vacancies SET status=?, status_at=? WHERE id=?", (status, now_iso(), vid))

    def recover_stale(self) -> int:
        """Tras un reinicio: los IN_PROGRESS vencidos con clic -> SUBMISSION_UNKNOWN; sin clic -> FAILED."""
        n = 0
        for v in self._q("SELECT * FROM vacancies WHERE status='IN_PROGRESS'"):
            if self._lock_expired(v):
                self.finish(v["id"], "failed", "recuperado tras reinicio")
                n += 1
        return n

    def stats(self) -> dict:
        by = {r["status"]: r["n"] for r in self._q("SELECT status, COUNT(*) n FROM vacancies GROUP BY status")}
        multi = self._q("SELECT COUNT(*) n FROM (SELECT vacancy_id FROM vacancy_sources GROUP BY vacancy_id "
                        "HAVING COUNT(*)>1)")[0]["n"]
        return {"vacancies": sum(by.values()), "by_status": by, "multi_source": multi,
                "employers": self._q("SELECT COUNT(*) n FROM employers")[0]["n"],
                "sources": self._q("SELECT COUNT(*) n FROM vacancy_sources")[0]["n"]}

    # -------------------------------------------------- importación del historial
    def import_history(self, db) -> dict:
        """Importa applications (historial previo) al registro. Idempotente."""
        counts: dict[str, int] = {}
        for r in db.list():
            if not r.get("url"):
                continue
            ev = " ".join(e.get("message", "") for e in db.events(r["job_id"]))
            st = r["status"]
            if st in ("applied", "screening", "interview", "technical", "offer", "hired", "rejected", "withdrawn"):
                status = "SUBMITTED_CONFIRMED"
            elif st == "needs_input":
                status = "PENDING_REVIEW"
            elif st == "awaiting_review":
                status = "SUBMISSION_UNKNOWN" if ("Pulsé Enviar" in (r.get("status_detail") or "") or "Clicked Submit" in (r.get("status_detail") or "")) else "PENDING_REVIEW"
            elif st == "error":
                status = "FAILED"
            elif st in ("skipped", "cancelled"):
                status = "CLOSED"
            else:
                status = "QUALIFIED"
            v = self.register(r["url"], r.get("company"), r.get("title"), r.get("country"), r.get("city"),
                              r.get("modality"), source=r.get("platform"), status=status, job_id=r["job_id"])
            if v["status"] != status and v["status"] != "SUBMITTED_CONFIRMED":
                self.set_status(v["id"], status)
            if status == "SUBMITTED_CONFIRMED" and not v.get("submitted_at"):
                conf = (r.get("data") or {}).get("confirmation") or ("detectada en el portal" if ("ya postulaste" in ev or "already applied" in ev)
                                                                     else "historial")
                with self._lock:
                    self._conn.execute("UPDATE vacancies SET submitted_at=?, confirmation=? WHERE id=?",
                                       (r.get("applied_at") or now_iso(), conf, v["id"]))
            counts[status] = counts.get(status, 0) + 1
        return counts
