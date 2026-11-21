"""Estructura la sección de experiencia de un CV importado en un borrador de `experience` con logros e ids.

Heurística, pensada para ahorrar tipeo y NUNCA para afirmar nada: el borrador siempre pide revisión humana, las
skills detectadas quedan `to_demonstrate` y la evidencia sugerida no cuenta como evidencia hasta que el candidato
la confirme en `candidate/profile.yaml`.
"""
from __future__ import annotations

import re

from .taxonomy import Taxonomy
from .utils import normalize

_DATE = (r"(?:\d{4}[-/]\d{1,2}|(?:\d{1,2}[/-])?\d{4}|[A-Za-z]{3,9}\.?\s+(?:de\s+)?\d{4})")
RANGE = re.compile(rf"(?P<s>{_DATE})\s*(?:-|–|—|a|to|hasta)\s*(?P<e>presente|actual|actualidad|present|current|{_DATE})",
                   re.IGNORECASE)
BULLET = re.compile(r"^\s*(?:[-•*·–—▪●◦]|\d+[.)])\s+")
MONTHS = {"ene": 1, "jan": 1, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
          "aug": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12, "dec": 12}
PRESENT = {"presente", "actual", "actualidad", "present", "current"}


def to_month(token: str) -> str:
    """'2021-03' / '03/2021' / 'marzo 2021' -> '2021-03'; '2019' -> '2019'; 'actual' -> 'presente'; otro -> ''."""
    tok = normalize(token).strip(" .")
    if tok in PRESENT:
        return "presente"
    if m := re.fullmatch(r"(\d{4})[-/](\d{1,2})", tok):
        return f"{m.group(1)}-{int(m.group(2)):02d}" if 1 <= int(m.group(2)) <= 12 else ""
    if m := re.fullmatch(r"(\d{1,2})[/-](\d{4})", tok):
        return f"{m.group(2)}-{int(m.group(1)):02d}" if 1 <= int(m.group(1)) <= 12 else ""
    if re.fullmatch(r"\d{4}", tok):
        return tok
    if m := re.fullmatch(r"([a-z]{3,9})\.? (?:de )?(\d{4})", tok):
        month = MONTHS.get(m.group(1)[:3])
        return f"{m.group(2)}-{month:02d}" if month else ""
    return ""


def _split_header(text: str) -> tuple[str, str]:
    """'Analista - Minera X' / 'Analista | Minera X' / 'Analista @ X' -> (cargo, empresa)."""
    parts = re.split(r"\s+[|@–—-]\s+", text.strip(" -–—|,"), maxsplit=1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (text.strip(" -–—|,"), "")


def structure_experience(lines: list[str], taxonomy: Taxonomy) -> list[dict]:
    """Líneas de la sección de experiencia -> [{id, company, role, start, end, achievements: [{id, text, skills}]}]."""
    range_idx = {i for i, ln in enumerate(lines) if RANGE.search(ln)}
    header_of: dict[int, int] = {}              # índice de línea de fechas -> índice de la línea de cargo/empresa
    for i in range_idx:
        prev = i - 1
        if prev >= 0 and prev not in range_idx and not BULLET.match(lines[prev]):
            header_of[i] = prev
    consumed = set(header_of.values())

    entries: list[dict] = []
    n_ach = 0
    for i, line in enumerate(lines):
        if i in consumed:
            continue
        m = RANGE.search(line)
        if m:
            rest = (line[:m.start()] + " " + line[m.end():]).strip(" -–—|,()")
            header = lines[header_of[i]] if i in header_of else rest
            role, company = _split_header(header)
            if i in header_of and rest and not company:
                company = rest
            entries.append({"id": f"exp-{len(entries) + 1}", "company": company, "role": role,
                            "start": to_month(m.group("s")), "end": to_month(m.group("e")), "achievements": []})
            continue
        if entries:
            text = BULLET.sub("", line).strip()
            if len(text) < 8:
                continue
            n_ach += 1
            skills = sorted((taxonomy.name(k) for k in taxonomy.find_in(text)), key=str.lower)
            entries[-1]["achievements"].append({"id": f"ach-{n_ach}", "text": text, "skills": skills})
    return entries


def suggest_evidence(experience: list[dict]) -> dict[str, list[str]]:
    """{nombre de skill: [ids de logros donde aparece]}: solo sugerencias para que el candidato confirme."""
    out: dict[str, list[str]] = {}
    for exp in experience:
        for ach in exp["achievements"]:
            for skill in ach["skills"]:
                out.setdefault(skill, []).append(ach["id"])
    return out
