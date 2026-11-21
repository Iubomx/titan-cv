"""Avisos de calidad del perfil (no bloquean): formato, fechas, claves desconocidas y evidencia débil.

Son consejos para que el perfil sea defendible en entrevista; los errores que impiden generar CV siguen en
`Profile.validate`.
"""
from __future__ import annotations

import re
from datetime import date

from .i18n import t

KNOWN_KEYS = {"personal", "summary", "summary_variants", "experience", "projects", "education", "certifications",
              "skills", "preferences", "documents", "languages", "cv_files", "_import", "detected_skills",
              "raw_sections"}
ONGOING = {"", "presente", "actual", "actualidad", "present", "current", "now", "none"}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE = re.compile(r"^(\d{4})(?:[-/](\d{1,2}))?$")


def _month(value, default: date) -> date | None:
    """Fecha del perfil como primer día del mes; None si el formato no es válido; `default` si sigue vigente."""
    if value is None or str(value).strip().lower() in ONGOING:
        return default
    m = DATE.match(str(value).strip())
    if not m or not 1 <= int(m.group(2) or 1) <= 12:
        return None
    return date(int(m.group(1)), int(m.group(2) or 1), 1)


def check(data: dict, today: date | None = None) -> list[str]:
    today = today or date.today()
    out: list[str] = []

    email = (data.get("personal") or {}).get("email")
    if email and not EMAIL.match(str(email).strip()):
        out.append(t("profile.email_invalid", value=email))

    for key in sorted(set(data) - KNOWN_KEYS):
        out.append(t("profile.unknown_key", key=key))

    spans = []
    for exp in data.get("experience") or []:
        label = exp.get("id") or exp.get("company") or "?"
        start, end = _month(exp.get("start"), today), _month(exp.get("end"), today)
        if exp.get("start") is not None and start is None:
            out.append(t("profile.date_invalid", item=label, value=exp.get("start")))
        if exp.get("end") is not None and end is None:
            out.append(t("profile.date_invalid", item=label, value=exp.get("end")))
        if start and end:
            if end < start:
                out.append(t("profile.date_order", item=label))
            else:
                spans.append((start, end, label))
        for ach in exp.get("achievements") or []:
            if not re.search(r"\d", str(ach.get("text") or "")):
                out.append(t("profile.achievement_no_figures", item=ach.get("id") or label))

    spans.sort()
    for (_s1, e1, l1), (s2, _e2, l2) in zip(spans, spans[1:]):
        if s2 < e1:
            out.append(t("profile.overlapping_experience", a=l1, b=l2))

    for skill in data.get("skills") or []:
        if skill.get("status") == "backed" and len(skill.get("evidence") or []) == 1:
            out.append(t("profile.skill_single_evidence", name=skill.get("name")))
    return out
