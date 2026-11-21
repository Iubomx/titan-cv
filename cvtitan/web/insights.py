"""Datos para las vistas de la web: embudo de la última misión, agenda y resumen semanal (solo lectura)."""
from __future__ import annotations

import csv
from pathlib import Path

from ..funnel import TIERS, summarize

TIER_ORDER = {tier: i for i, tier in enumerate(("high", "held", "manual", "potential", "review", "no"))}
POINT_COLUMNS = ("pts_compatibility", "pts_eligibility", "pts_salary", "pts_experience")


def _number(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def latest_funnel(runs_dir: Path, limit: int = 40) -> dict:
    """Embudo del último `*-funnel.csv` (sin URLs: solo códigos). `file: None` si aún no hay misiones."""
    files = sorted(runs_dir.glob("*-funnel.csv")) if runs_dir.is_dir() else []
    if not files:
        return {"file": None, "total": 0, "tiers": {t: 0 for t in TIERS}, "reasons": {}, "rows": []}
    path = files[-1]
    with path.open(encoding="utf-8-sig", newline="") as fh:
        records = list(csv.DictReader(fh, delimiter=";"))
    summary = summarize(records)
    rows = []
    for r in sorted(records, key=lambda r: (TIER_ORDER.get(r.get("tier") or "no", 9), -(_number(r.get("score")) or 0))):
        row = {k: r.get(k) or "" for k in ("line", "tier", "reason_category", "reason", "title", "company", "source", "ref")}
        row["score"] = _number(r.get("score"))
        row["points"] = {k.removeprefix("pts_"): _number(r.get(k)) for k in POINT_COLUMNS if _number(r.get(k)) is not None}
        rows.append(row)
    return {"file": path.name, "total": len(records), "tiers": summary["tiers"], "reasons": summary["reasons"],
            "rows": rows[:limit]}
