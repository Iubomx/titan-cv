"""Informe semanal de la búsqueda: envíos, respuestas, tiempo hasta la primera respuesta y agenda.

Solo usa datos reales del historial (`data/cvtitan.db`): nada simulado. Las URLs no se muestran.
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

from .db import ADVANCED, DB, PROCESS_STATUSES, STATUS_LABELS

ADVANCED_LABELS = tuple(STATUS_LABELS[s] for s in ADVANCED)


def _day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _first_response_days(db: DB, row: dict) -> float | None:
    """Días entre el envío y el primer estado de avance (revisión, entrevista...). None si aún no hubo."""
    applied = row.get("applied_at")
    if not applied:
        return None
    for event in db.events(row["job_id"]):
        if event["kind"] == "status" and event["message"].startswith(ADVANCED_LABELS):
            try:
                delta = datetime.fromisoformat(event["ts"]) - datetime.fromisoformat(applied)
            except ValueError:
                return None
            return round(max(0.0, delta.total_seconds() / 86400), 1)
    return None


def build(db: DB, days: int = 7, today: date | None = None) -> dict:
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    rows = [r for r in db.list() if r.get("status") in PROCESS_STATUSES]
    in_window = [r for r in rows if (d := _day(r.get("applied_at"))) and start <= d <= today]
    per_day = {(start + timedelta(days=i)).isoformat(): 0 for i in range(days)}
    for r in in_window:
        per_day[str(r["applied_at"])[:10]] += 1
    advanced = [r for r in in_window if r["status"] in ADVANCED]
    waits = [w for r in in_window if (w := _first_response_days(db, r)) is not None]
    companies: dict[str, int] = {}
    for r in in_window:
        name = r.get("company") or "-"
        companies[name] = companies.get(name, 0) + 1
    by_status: dict[str, int] = {}
    for r in in_window:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    return {
        "from": start.isoformat(), "to": today.isoformat(), "days": days, "sent": len(in_window),
        "per_day": per_day, "by_status": by_status, "advanced": len(advanced),
        "response_rate": round(100 * len(advanced) / len(in_window), 1) if in_window else None,
        "median_days_to_response": round(statistics.median(waits), 1) if waits else None,
        "top_companies": sorted(companies.items(), key=lambda kv: (-kv[1], kv[0]))[:5],
        "agenda": db.agenda(days=7, today=today),
    }


def render(data: dict) -> str:
    rate = f"{data['response_rate']}%" if data["response_rate"] is not None else "n/a"
    wait = f"{data['median_days_to_response']} days" if data["median_days_to_response"] is not None else "n/a"
    lines = ["=" * 60, f"TITAN CV - WEEKLY REPORT  {data['from']} .. {data['to']}".center(60), "=" * 60,
             f"Applications sent: {data['sent']}   Advanced (screening or beyond): {data['advanced']}",
             f"Response rate: {rate}   Median time to first response: {wait}", "", "Per day:"]
    lines += [f"  {d}  {'#' * n}{' ' if n else ''}{n}" for d, n in data["per_day"].items()]
    if data["by_status"]:
        lines += ["", "By status:"] + [f"  {STATUS_LABELS.get(s, s):<24} {n}" for s, n in sorted(data["by_status"].items())]
    if data["top_companies"]:
        lines += ["", "Most applications:"] + [f"  {name[:30]:<30} {n}" for name, n in data["top_companies"]]
    lines += ["", "Next 7 days (and overdue):"]
    if not data["agenda"]:
        lines.append("  Nothing scheduled. Add milestones with `cvtitan track event`.")
    for e in data["agenda"]:
        flag = "OVERDUE " if e["due"] < data["to"] else ""
        lines.append(f"  {e['due']} {flag}{e['kind']:<10} {(e.get('company') or '-')[:22]:<22} {e.get('title') or e['job_id']}")
    lines.append("=" * 60)
    return "\n".join(lines)
