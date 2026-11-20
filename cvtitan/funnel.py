"""Embudo de cada oferta: nivel de compatibilidad y motivo categorizado (auditoría 2026-11-18).

Niveles (configurables, sin inflar coincidencias):
  high      pasa TODAS las reglas (se postula si hay cupo y el registro lo permite)
  held      compatible, pero quedó fuera por el cupo diario o porque el registro la tiene pendiente
  manual    compatible, pero el portal bloquea la automatización: postular a mano
  potential solo le falta puntaje: está a `margin` puntos o menos del mínimo (ninguna otra regla falla)
  review    en espera de algo externo: cuenta del portal, CAPTCHA, persona
  no        no compatible (con su motivo)
Cada oferta queda en el archivo <fecha>-funnel.csv de la ejecución (URL solo como código; la URL real queda en
data/auto/refs.json, local, para `cvtitan informe --ref`).
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

TIERS = ("high", "held", "manual", "potential", "review", "no")
TIER_LABEL = {"high": "HIGH", "held": "HELD", "manual": "MANUAL", "potential": "POTENTIAL", "review": "REVIEW",
              "no": "NO"}

# Motivo -> categoría (español e inglés; Línea A y Línea B).
REASONS = [
    ("daily cap", r"daily cap|tope diario"),
    ("registry: pending/sent", r"registry|already sent|ya enviada|ya revisada|already reviewed"),
    ("portal blocks automation", r"bloquea la automat|blocks automation"),
    ("board account required", r"exige cuenta del portal|requires a board account"),
    ("captcha / human step", r"captcha|requiere persona|needs a human"),
    ("off-target role", r"fuera de tus roles|off-target|cargo fuera"),
    ("excluded title (junior, sales...)", r"cargo excluido|excluded title"),
    ("score below threshold", r"ajuste [\d.]+ <|puntaje [\d.]+ <|score below"),
    ("salary below expectation", r"sueldo|salary"),
    ("not eligible from Chile", r"no se puede trabajar desde chile|excluido|presencial en|not eligible|restringe"),
    ("temporary / project", r"temporal|reemplazo|project"),
    ("duplicate across boards", r"duplicad|duplicate"),
]


def reason_category(motivo: str) -> str:
    m = (motivo or "").lower()
    for name, rx in REASONS:
        if re.search(rx, m):
            return name
    return "other" if m else ""


def tier_line_a(decision: str, motivo: str, score: float | None, min_score: float, margin: float,
                manual_ok: bool = False) -> str:
    cat = reason_category(motivo)
    if decision == "postular":
        return "high"
    if cat in ("daily cap", "registry: pending/sent"):
        return "held"
    if cat == "portal blocks automation":
        return "manual" if manual_ok else "no"
    if cat == "score below threshold" and score is not None and score >= min_score - margin:
        return "potential"
    return "no"


def tier_line_b(decision: str, motivo: str, score: float | None, min_score: float, margin: float) -> str:
    cat = reason_category(motivo)
    if decision == "postular":
        return "high"
    if decision in ("en espera", "requiere persona"):
        return "held" if cat == "daily cap" else "review"
    if cat == "score below threshold" and score is not None and score >= min_score - margin:
        return "potential"
    return "no"


def write(records: list[dict], path: Path, refs_path: Path) -> None:
    """Guarda el embudo (sin URLs) y actualiza el mapa local código -> URL."""
    from .privacy import mask_url, redact, ref
    cols = ["line", "stage", "tier", "reason_category", "reason", "score", "title", "company", "source", "country",
            "modality", "ref", "pts_compatibility", "pts_eligibility", "pts_salary", "pts_experience"]
    refs: dict[str, str] = {}
    if refs_path.exists():
        try:
            refs = json.loads(refs_path.read_text(encoding="utf-8"))
        except ValueError:
            refs = {}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for r in records:
            url = r.get("url") or ""
            if url:
                refs[ref(url)] = url
            w.writerow({**{k: redact("" if r.get(k) is None else str(r.get(k))) for k in cols},
                        "ref": mask_url(url) if url else ""})
    refs_path.write_text(json.dumps(refs, ensure_ascii=False), encoding="utf-8")


def summarize(records: list[dict]) -> dict:
    tiers = {t: 0 for t in TIERS}
    reasons: dict[str, int] = {}
    for r in records:
        tiers[r.get("tier") or "no"] = tiers.get(r.get("tier") or "no", 0) + 1
        if r.get("tier") == "no" and r.get("reason_category"):
            reasons[r["reason_category"]] = reasons.get(r["reason_category"], 0) + 1
    return {"tiers": tiers, "reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1]))}
