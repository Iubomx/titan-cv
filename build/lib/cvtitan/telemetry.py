"""Estado REAL de una ejecución y bus de eventos (lado del negocio, sin dependencias de interfaz).

El motor (autopilot, line_b, BatchApplier) informa aquí lo que ocurre. Cada cambio se publica como un evento a los
suscriptores (`subscribe`), sin bloquear al motor: las interfaces —el centro de mando de `cvtitan/ui/`, un log, una
web— solo LEEN. Ninguna métrica se inventa: si el motor no la informó, la interfaz muestra «—».
"""
from __future__ import annotations

import re
import threading
import time
from collections import Counter, deque
from datetime import date, datetime
from pathlib import Path
from typing import Callable

# Contadores de la misión (se acumulan entre la Línea A y la B en `--linea todas`).
COUNTERS = {
    "discovered": "Offers discovered",
    "analyzed": "Offers analyzed",
    "compatible": "Compatible (all rules)",
    "held_quota": "  held: quota/registry",
    "manual_apply": "  apply manually",
    "potential": "Potential (near score)",
    "on_hold": "On hold (account/CAPTCHA)",
    "applied": "Applications confirmed",
    "pending": "Pending (needs you)",
    "discarded": "Not compatible",
    "duplicates": "Duplicates avoided",
    "done_before": "Already sent (skipped)",
    "errors": "Errors",
}

# Los 7 agentes del sistema y qué parte REAL del motor representa cada uno.
AGENTS = {
    "TITAN-CORE": "orchestration of the mission",
    "TITAN-SCOUT": "offer discovery on job boards and ATS",
    "TITAN-RADAR": "geographic exploration",
    "TITAN-SHIELD": "validation, legal guard and duplicate prevention",
    "TITAN-MATCH": "professional fit evaluation",
    "TITAN-APPLY": "authorized application processing",
    "TITAN-MEMORY": "persistence and history",
}
# Nombres internos que ya usa el motor -> agente del centro de mando.
ALIASES = {"Scout de portales": "TITAN-SCOUT", "Job Intelligence": "TITAN-MATCH", "Evidence Match": "TITAN-MATCH",
           "Robot de formularios": "TITAN-APPLY"}
STATUS_EN = {"ACTIVO": "ACTIVE", "LISTO": "READY", "EN ESPERA": "STANDBY", "OFF": "OFFLINE", "EN LÍNEA": "ONLINE",
             "ALERTA": "ALERT"}

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_ERR = re.compile(r"(?i)\berror\b|traceback|exception|runtimeerror|timeouterror|\bfailed\b|\[fail\]|^alert ")
_WARN = re.compile(r"(?i)pending|skipped|circuit|daily cap|no results|not eligible|captcha|\[pend\]|interrupt|"
                   r"pendiente|omitid|circuito|tope|sin resultados|no elegible|requiere persona|en espera")
_SUMMARY = re.compile(r"offers -> \d+ candidates|eligibility: \{|^\s*applied \d+ \||^\s*\[[#-]{4}|"
                      r"already reviewed, skipped|(?i:daily cap of \d+ linkedin)|search cap reached|explored recently|"
                      r"^\s*\[(SENT|DONE|PEND|SKIP|FAIL)\] \[")

# Nombres de país en inglés (las fuentes entregan códigos ISO o nombres en español).
COUNTRY = {"CL": "Chile", "AR": "Argentina", "PE": "Peru", "CO": "Colombia", "MX": "Mexico", "US": "United States",
           "BR": "Brazil", "ES": "Spain", "CA": "Canada", "UY": "Uruguay", "EC": "Ecuador", "BO": "Bolivia",
           "PY": "Paraguay", "VE": "Venezuela", "AU": "Australia", "GB": "United Kingdom", "DE": "Germany",
           "IE": "Ireland", "NL": "Netherlands", "PT": "Portugal", "PL": "Poland", "NZ": "New Zealand",
           "SG": "Singapore", "AE": "United Arab Emirates", "Canadá": "Canada", "México": "Mexico", "Perú": "Peru",
           "Brasil": "Brazil", "España": "Spain", "Estados Unidos": "United States", "Alemania": "Germany",
           "Reino Unido": "United Kingdom", "Unión Europea": "European Union", "the United States": "United States"}


def country_en(name: str) -> str:
    name = (name or "").strip()
    return COUNTRY.get(name, COUNTRY.get(name.upper(), name))


class RunState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.listeners: list[Callable[[dict], None]] = []
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.started = time.time()
            self.mission = ""
            self.mode = ""
            self.line = ""
            self.stage = "Standby"
            self.stage_n = 0
            self.stage_total = 0
            self.counters: Counter = Counter()
            self.portals: dict[str, str | int] = {}
            self.countries: set[str] = set()
            self.cities: set[str] = set()
            self.companies: set[str] = set()
            self.agents: dict[str, tuple[str, str]] = {a: ("STANDBY", "") for a in AGENTS}
            self.system: dict[str, tuple[str, str]] = {}
            self.active_agent = "TITAN-CORE"
            self.apply_total = 0
            self.apply_done = 0
            self.current = ""
            self.visited: Counter = Counter()          # dominio -> páginas consultadas
            self.market: dict[str, Counter] = {k: Counter() for k in
                                               ("source", "company", "country", "city", "modality", "fit")}
            self.salaries: list[float] = []            # sueldos publicados (USD/mes) de las ofertas analizadas
            self.funnel: list[dict] = []               # recorrido de cada oferta (cvtitan/funnel.py)
            self.reasons: Counter = Counter()          # motivo categorizado de cada «no compatible»
            self.cache_reads = 0                       # lecturas desde la caché del día (no son visitas)
            self.market_total = 0
            self.processed: list[dict] = []            # vacantes procesadas por el robot (url, título, resultado)
            self.events: deque = deque(maxlen=1000)
            self.alerts: deque = deque(maxlen=300)
            self.finished = False


STATE = RunState()


# ------------------------------------------------------------------ bus de eventos
def subscribe(fn: Callable[[dict], None]) -> Callable[[], None]:
    """Registra un oyente (debe ser rápido y no bloquear). Devuelve la función para desuscribirse."""
    with STATE.lock:
        STATE.listeners.append(fn)

    def unsubscribe() -> None:
        with STATE.lock:
            if fn in STATE.listeners:
                STATE.listeners.remove(fn)
    return unsubscribe


def record_to(path: Path) -> Callable[[], None]:
    """Guarda cada evento de texto de la ejecución en `path` (con hora, nivel y agente). Devuelve el cierre."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a", encoding="utf-8", buffering=1)

    def write(ev: dict) -> None:
        if ev["kind"] == "log":
            fh.write(f"{datetime.fromtimestamp(ev['t']):%H:%M:%S} {ev['level']:<5} {ev['agent']:<13} {ev['text']}\n")
        elif ev["kind"] in ("stage", "apply_result", "finish"):
            fh.write(f"{datetime.fromtimestamp(ev['t']):%H:%M:%S} EVENT {ev['kind']} "
                     f"{ {k: v for k, v in ev.items() if k not in ('t', 'kind')} }\n")
    unsubscribe = subscribe(write)

    def close() -> None:
        unsubscribe()
        fh.close()
    return close


def _publish(kind: str, **data) -> None:
    event = {"t": time.time(), "kind": kind, **data}
    for fn in list(STATE.listeners):
        try:
            fn(event)
        except Exception:                   # un oyente con fallas nunca detiene al motor
            pass


# ------------------------------------------------------------------ escritura (desde el motor)
def log(message: str = "", level: str | None = None) -> None:
    """Sustituto de `print`/`say`: registra el evento con hora y agente. Detecta errores y alertas."""
    from .privacy import redact                 # ningún evento (pantalla, tablero, registro) lleva datos personales
    message = redact(str(message))
    text = _ANSI.sub("", message).rstrip()
    raw = message.rstrip("\n")
    if not text.strip():
        return
    lvl = level or ("error" if _ERR.search(text) else
                    "warn" if _WARN.search(text) and not _SUMMARY.search(text) else "info")
    ts = datetime.now().strftime("%H:%M:%S")
    with STATE.lock:
        agent_name = STATE.active_agent
        for line in raw.splitlines():
            if _ANSI.sub("", line).strip():
                STATE.events.append((ts, lvl, line, agent_name))
        if lvl in ("warn", "error"):
            STATE.alerts.append((ts, lvl, text.strip()[:300]))
    _publish("log", level=lvl, text=text, agent=agent_name)


def mission(name: str, mode: str = "") -> None:
    with STATE.lock:
        STATE.mission = name
        STATE.mode = mode or STATE.mode
        STATE.agents["TITAN-CORE"] = ("ONLINE", name)
    _publish("mission", name=name, mode=mode)


def stage(line: str, n: int, total: int, label: str) -> None:
    with STATE.lock:
        STATE.line, STATE.stage_n, STATE.stage_total, STATE.stage = line, n, total, label
        STATE.agents["TITAN-CORE"] = ("ACTIVE", f"{line} · phase {n}/{total}")
    _publish("stage", line=line, n=n, total=total, label=label)


def count(name: str, n: int = 1) -> None:
    with STATE.lock:
        STATE.counters[name] += int(n)
        if name in ("duplicates", "done_before") and n:
            blocked = STATE.counters["duplicates"] + STATE.counters["done_before"]
            STATE.agents["TITAN-SHIELD"] = ("ACTIVE", f"{blocked} duplicates blocked")
    _publish("count", name=name, n=n)


def portal(name: str, result) -> None:
    with STATE.lock:
        STATE.portals[name] = len(result) if isinstance(result, list) else result
    _publish("portal", name=name)


def explored(countries=(), cities=(), companies=()) -> None:
    with STATE.lock:
        STATE.countries.update(country_en(c) for c in countries if c and c.strip())
        STATE.cities.update(c for c in cities if c)
        STATE.companies.update(c.strip() for c in companies if c and c.strip())
        if STATE.countries or STATE.cities:
            STATE.agents["TITAN-RADAR"] = ("ACTIVE", f"{len(STATE.countries)} countries · {len(STATE.cities)} cities")
    _publish("explored")


def agent(name: str, status: str, detail: str = "") -> None:
    name = ALIASES.get(name, name)
    status = STATUS_EN.get(status, status)
    with STATE.lock:
        STATE.agents[name] = (status, detail)
        if status == "ACTIVE":
            STATE.active_agent = name
    _publish("agent", name=name, status=status, detail=detail)


def system(name: str, status: str, detail: str = "") -> None:
    """Componentes del sistema que no son agentes (motor de IA, guardia de LinkedIn)."""
    with STATE.lock:
        STATE.system[name] = (STATUS_EN.get(status, status), detail)


def apply_begin(total: int) -> None:
    with STATE.lock:
        STATE.apply_total += int(total)
    _publish("apply_begin", total=total)


def apply_item(title: str) -> None:
    with STATE.lock:
        STATE.current = title
        STATE.active_agent = "TITAN-APPLY"
    _publish("apply_item", title=title)


def funnel(records: list[dict]) -> None:
    """Registra el embudo: cada registro trae tier (high/held/manual/potential/review/no) y reason_category."""
    tier_counter = {"held": "held_quota", "manual": "manual_apply", "potential": "potential", "review": "on_hold",
                    "no": "discarded"}
    with STATE.lock:
        STATE.funnel.extend(records)
        for r in records:
            t = r.get("tier") or "no"
            if t in ("high", "held", "manual"):
                STATE.counters["compatible"] += 1
            if t in tier_counter:
                STATE.counters[tier_counter[t]] += 1
            if t == "no" and r.get("reason_category"):
                STATE.reasons[r["reason_category"]] += 1
    _publish("funnel", n=len(records))


def cache_read() -> None:
    with STATE.lock:
        STATE.cache_reads += 1


FIT_BUCKETS = ((80, "80-100"), (65, "65-79"), (50, "50-64"), (35, "35-49"), (0, "0-34"))


def market(offers: list[dict]) -> None:
    """Inteligencia de mercado REAL: cada oferta analizada (aunque no se postule) suma a los agregados.
    Claves aceptadas: source, company, country, city, modality, fit (0-100), salary_usd (mensual)."""
    with STATE.lock:
        m = STATE.market
        for o in offers:
            STATE.market_total += 1
            for k in ("source", "company", "city", "modality"):
                v = str(o.get(k) or "").strip()
                if v:
                    m[k][v[:40]] += 1
            if o.get("country"):
                m["country"][country_en(str(o["country"]))] += 1
            if o.get("fit") not in (None, ""):
                try:
                    f = float(o["fit"])
                    m["fit"][next(lbl for lo, lbl in FIT_BUCKETS if f >= lo)] += 1
                except (TypeError, ValueError):
                    pass
            if o.get("salary_usd"):
                try:
                    STATE.salaries.append(float(o["salary_usd"]))
                except (TypeError, ValueError):
                    pass
    _publish("market", n=len(offers))


def visit(url: str) -> None:
    """Página consultada (listado, aviso o formulario). Se cuenta por dominio para el informe final."""
    from urllib.parse import urlparse
    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    if host:
        with STATE.lock:
            STATE.visited[host] += 1


def apply_result(result: str, title: str = "", url: str = "") -> None:
    from .colors import kind
    k = kind(result)
    with STATE.lock:
        STATE.processed.append({"time": datetime.now().strftime("%H:%M:%S"), "url": url or STATE.current,
                                "title": title, "result": result, "outcome": k})
        STATE.apply_done += 1
        STATE.current = ""
        STATE.counters[{"ok": "applied", "done": "done_before", "pend": "pending", "err": "errors",
                        "no": "discarded"}[k]] += 1
        st, detail = STATE.agents.get("TITAN-MEMORY", ("READY", ""))
        STATE.agents["TITAN-MEMORY"] = ("ACTIVE", f"{STATE.apply_done} outcome(s) recorded")
        if k == "done":
            blocked = STATE.counters["duplicates"] + STATE.counters["done_before"]
            STATE.agents["TITAN-SHIELD"] = ("ACTIVE", f"{blocked} duplicates blocked")
    _publish("apply_result", result=result, outcome=k)


def finish() -> None:
    with STATE.lock:
        STATE.finished = True
        STATE.stage = "Mission complete"
        for a, (st, d) in list(STATE.agents.items()):
            if st == "ACTIVE":
                STATE.agents[a] = ("READY", d)
        c = STATE.counters
        totals = {      # resumen acumulado de TODA la misión (todas las líneas), no solo de la última fase
            "TITAN-CORE": "mission complete",
            "TITAN-SCOUT": f"{c['discovered']} offers · {len(STATE.portals)} portals" if c["discovered"] else None,
            "TITAN-MATCH": f"{c['analyzed']} analyzed · {c['compatible']} compatible" if c["analyzed"] else None,
            "TITAN-SHIELD": f"{c['duplicates'] + c['done_before']} duplicates blocked",
            "TITAN-APPLY": f"{STATE.apply_done} processed · {c['applied']} confirmed" if STATE.apply_done else None,
            "TITAN-RADAR": f"{len(STATE.countries)} countries · {len(STATE.cities)} cities" if STATE.countries else None,
        }
        for a, detail in totals.items():
            if detail:
                STATE.agents[a] = ("READY", detail)
    _publish("finish")


def snapshot() -> dict:
    """Copia coherente del estado para dibujarla sin bloquear al motor."""
    with STATE.lock:
        s = STATE
        return {"started": s.started, "mission": s.mission, "mode": s.mode, "line": s.line, "stage": s.stage,
                "stage_n": s.stage_n, "stage_total": s.stage_total, "counters": dict(s.counters),
                "portals": dict(s.portals), "countries": sorted(s.countries), "cities": sorted(s.cities),
                "companies": len(s.companies), "agents": dict(s.agents), "system": dict(s.system),
                "active_agent": s.active_agent, "apply_total": s.apply_total, "apply_done": s.apply_done,
                "current": s.current, "events": list(s.events), "alerts": list(s.alerts), "finished": s.finished,
                "visited": dict(s.visited), "processed": list(s.processed),
                "market": {k: dict(v) for k, v in s.market.items()}, "salaries": list(s.salaries),
                "market_total": s.market_total, "reasons": dict(s.reasons), "cache_reads": s.cache_reads,
                "funnel_size": len(s.funnel)}


# ------------------------------------------------------------------ historial persistente (lectura de la BD)
def history(db_path: Path, ws_root: Path | None = None) -> dict:
    """Historial real: postulaciones de toda la vida, de hoy, últimas enviadas y control de duplicados."""
    from .db import DB, PROCESS_STATUSES
    out: dict = {"total": 0, "today": 0, "last": [], "registry": {}, "daily_max": None, "records": 0}
    try:
        db = DB(db_path)
        rows = db.list()
        out["records"] = len(rows)
        sent = [r for r in rows if r.get("status") in PROCESS_STATUSES]
        today = date.today().isoformat()
        out["total"] = len(sent)
        detected = [r for r in sent if re.search(r"(?i)already applied|ya postulaste", r.get("status_detail") or "")]
        out["already_applied"] = len(detected)                 # el portal detectó una postulación previa
        out["confirmed"] = len(sent) - len(detected)           # envío del robot confirmado por la plataforma
        out["today"] = sum(1 for r in sent if str(r.get("applied_at") or "").startswith(today))
        sent.sort(key=lambda r: str(r.get("applied_at") or ""), reverse=True)
        out["last"] = [(str(r.get("applied_at") or "")[:10], r.get("company") or "—", r.get("title") or "—")
                       for r in sent[:8]]
    except Exception as e:                                  # la interfaz nunca debe caer por la BD
        out["error"] = str(e)[:120]
    try:
        from .registry import Registry
        out["registry"] = Registry(db_path).stats()
    except Exception:
        pass
    if ws_root:
        try:
            from .utils import load_yaml
            a = (load_yaml(ws_root / "config" / "auto.yaml") or {}).get("daily_max")
            b = ((load_yaml(ws_root / "config" / "lines.yaml") or {}).get("lines") or {}).get("B", {}).get("daily_max")
            out["daily_max"] = sum(int(x) for x in (a, b) if x)
        except Exception:
            pass
    return out


def llm_status(ws_root: Path) -> tuple[str, str]:
    """Mismo criterio que el motor: llm.enabled en config/settings.yaml + ANTHROPIC_API_KEY."""
    import os
    try:
        from .utils import load_yaml
        enabled = bool(((load_yaml(ws_root / "config" / "settings.yaml") or {}).get("llm") or {}).get("enabled"))
    except Exception:
        enabled = False
    if not enabled:
        return ("OFFLINE", "disabled in settings.yaml")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return ("ALERT", "ANTHROPIC_API_KEY missing")
    return ("ONLINE", "claude-opus-5-5")


def linkedin_status(ws_root: Path, use_linkedin: bool) -> tuple[str, str]:
    if not use_linkedin:
        return ("OFFLINE", "skipped (--sin-linkedin)")
    import json
    try:
        st = json.loads((ws_root / "data" / "linkedin_guard.json").read_text(encoding="utf-8"))
        n = st.get("searches", 0) if st.get("day") == date.today().isoformat() else 0
    except (OSError, ValueError):
        n = 0
    return ("READY", f"{n} searches today")
