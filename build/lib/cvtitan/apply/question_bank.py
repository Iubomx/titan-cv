"""Respuestas automáticas a preguntas de postulación (sin IA, sin inventar).

Dos fuentes, en este orden:
1. Diccionario `candidate/question_bank.yaml`: patrones -> respuesta (hechos del perfil o decisiones del candidato).
2. Motor de evidencias: preguntas sobre experiencia con tecnologías («¿qué nivel de SQL y BigQuery?»,
   «¿has trabajado con GA4?», «años de experiencia con Power BI»). Cada skill mencionada se cruza con el perfil:
     - respaldada  -> «Sí» + el hecho que la respalda (y años desde su primera evidencia);
     - no respaldada -> «No tengo experiencia profesional directa con X» + la skill equivalente que sí está
       respaldada (misma categoría de la taxonomía). Nunca se afirma algo que el perfil no prueba.
Lo que no calza con ninguna regla queda pendiente (None).
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from ..profile import Profile
from ..utils import load_yaml, normalize

BANK_FILE = "question_bank.yaml"
EXPERIENCE_Q = re.compile(
    r"experiencia|experience|nivel de|manejo|dominio|level|anos|years|has (trabajado|usado|utilizado|implementado|"
    r"desarrollado)|have you (worked|used|implemented|built|developed)|familiar|conocimiento|knowledge|proficien|"
    r"trabajado con|worked with|cuentas con|sabes")
YEARS_Q = re.compile(r"cuantos anos|anos de experiencia|how many years|years of experience")
EN_WORDS = re.compile(r"\b(you|your|do|have|are|what|how|years|experience|with|the|of)\b")
LEVELS = [  # (nivel, patrones de opción)
    ("advanced", r"avanzad|advanced|expert|experto|senior|alto"),
    ("intermediate", r"intermedi|intermediate|medio|moderate"),
    ("basic", r"basic|basico|principiante|beginner|bajo|elemental"),
    ("none", r"ningun|sin experiencia|no experience|none|nulo|no tengo|^no$"),
]
YES = r"^(si|sí|yes|y)\b"
NO = r"^(no)\b"


def _english(label: str) -> bool:
    return len(EN_WORDS.findall(normalize(label))) >= 2


class QuestionBank:
    def __init__(self, profile: Profile, path: Path | None = None):
        self.profile = profile
        self.entries = []
        self.error = None
        if path and path.exists():
            try:                         # un diccionario mal escrito nunca debe impedir llenar el formulario
                self.entries = (load_yaml(path) or {}).get("questions") or []
            except Exception as e:
                self.error = f"{path.name}: {str(e).splitlines()[0]}"
        self._compiled = []
        for e in self.entries:
            try:
                self._compiled.append((e, [re.compile(p) for p in e.get("patterns") or []]))
            except re.error as err:
                self.error = f"{e.get('id')}: invalid pattern ({err})"

    # ------------------------------------------------------------ hechos del perfil
    def facts(self) -> dict:
        d = self.profile.data
        exp = (d.get("experience") or [{}])[0]
        edu = next((e for e in d.get("education") or [] if str(e.get("year", "")).isdigit()), {}) or {}
        prefs = d.get("preferences") or {}
        langs = {normalize(l.get("name", "")): l.get("level", "") for l in d.get("languages") or []}
        avail = prefs.get("availability") or ""
        motivation = prefs.get("motivation_generic") or {}
        certs = ", ".join(f"{c.get('name')} ({c.get('issuer')}, {c.get('year')})" for c in d.get("certifications") or [])
        return {
            "motivation_es": " ".join(str(motivation.get("es", "")).split()),
            "motivation_en": " ".join(str(motivation.get("en", "")).split()),
            "certifications": certs, "degree_year": str(edu.get("year", "")),
            "years_total": str(int(self.profile.years_experience())),
            "current_role": exp.get("role", ""), "current_company": exp.get("company", ""),
            "degree": edu.get("degree", "").split(" (")[0], "institution": edu.get("institution", ""),
            "degree_en": prefs.get("degree_equivalence_en") or "",
            "availability_es": avail, "availability_en": "Immediately" if normalize(avail) == "inmediata" else avail,
            "salary_es": prefs.get("salary_statement_es", ""), "salary_en": prefs.get("salary_statement_en", ""),
            "location": (d.get("personal") or {}).get("location", ""),
            "english_level": langs.get("ingles", ""),
        }

    # ------------------------------------------------------------ 1) diccionario
    def from_bank(self, field: dict, label: str) -> str | None:
        norm = normalize(label).strip(" *:?¿")
        opts = field.get("options") or []
        for entry, pats in self._compiled:
            if not any(p.search(norm) for p in pats):
                continue
            if "option" in entry and opts:
                for pat in entry["option"]:
                    for o in opts:
                        if re.search(pat, normalize(o)):
                            return o
            if "yesno" in entry and (opts or field.get("type") in ("select", "radio")):
                return _yes_no_option(opts, bool(entry["yesno"]))
            if opts and entry.get("answer"):
                first = normalize((entry["answer"].get("es") or "").split()[0] if entry["answer"].get("es") else "")
                if first.startswith(("si", "no")):
                    return _yes_no_option(opts, first.startswith("si"))
                return None
            ans = entry.get("answer")
            if ans:
                text = ans.get("en" if _english(label) else "es") or ans.get("es") or ""
                return text.format(**self.facts()).strip() or None
            if "yesno" in entry:
                truth = bool(entry["yesno"])
                return ("Yes" if truth else "No") if _english(label) else ("Sí" if truth else "No")
            return None                                      # entrada sin dato (p. ej. licencia): pendiente
        return None

    # ------------------------------------------------------------ 2) motor de evidencias
    def since_year(self, key: str) -> int | None:
        """Año de la primera evidencia de la skill (inicio del cargo o año del proyecto)."""
        sk = self.profile.skill_map.get(key) or {}
        ev = self.profile.evidence()
        exps = {e["id"]: e for e in self.profile.data.get("experience") or []}
        projects = {p["id"]: p for p in self.profile.data.get("projects") or []}
        years = []
        for eid in sk.get("evidence") or []:
            e = ev.get(eid)
            if not e:
                continue
            exp_id = e.get("parent") if e["kind"] == "achievement" else eid if e["kind"] == "experience" else None
            if exp_id and exps.get(exp_id, {}).get("start"):
                years.append(int(str(exps[exp_id]["start"])[:4]))
            elif eid in projects:
                m = re.findall(r"\b(20\d\d)\b", f"{projects[eid].get('name', '')} {projects[eid].get('description', '')}")
                if m:
                    years.append(min(int(y) for y in m))
        return min(years) if years else None

    def evidence_text(self, key: str) -> str:
        sk = self.profile.skill_map.get(key) or {}
        ev = self.profile.evidence()
        for eid in sk.get("evidence") or []:
            if eid in ev and ev[eid]["kind"] in ("achievement", "project"):
                text = " ".join(ev[eid]["text"].split())
                return text if len(text) <= 220 else text[:217].rsplit(" ", 1)[0] + "…"
        return ""

    def equivalent(self, key: str) -> str | None:
        """Skill respaldada de la misma categoría (para reconocer una brecha sin quedarse en el «no»)."""
        tax = self.profile.tax
        cat = tax.skills[key].category if key in tax.skills else None
        related = {"data": ("sql_server", "sql", "postgresql"), "bi": ("power_bi", "excel"),
                   "analytics": ("data_visualization", "reporting", "power_bi"), "database": ("sql_server", "postgresql"),
                   "cloud": ("docker",), "language": ("python", "typescript"), "frontend": ("react", "typescript"),
                   "backend": ("fastapi", "rest_api", "python"), "devops": ("docker", "git"),
                   "ai": ("anomaly_detection", "python"), "domain": ("dispatch", "autonomous_ops")}.get(cat or "", ())
        for k in related:
            if k != key and self.profile.is_backed(k):
                return k
        return None

    def from_evidence(self, field: dict, label: str) -> str | None:
        norm = normalize(label)
        if not EXPERIENCE_Q.search(norm):
            return None
        tax = self.profile.tax
        keys = [k for k in tax.find_in(label) if k not in ("mining",) or "mineria" in norm or "mining" in norm]
        if not keys:
            return None
        en = _english(label)
        backed = [k for k in keys if self.profile.is_backed(k)]
        missing = [k for k in keys if k not in backed]
        this_year = date.today().year
        yrs = {k: max(1, this_year - y) for k in backed if (y := self.since_year(k))}
        opts = field.get("options") or []

        if YEARS_Q.search(norm) and field.get("type") in ("number", "text") and not opts:
            return str(max(yrs.values())) if yrs else ("0" if not backed else None)
        if opts:
            if any(re.search(YES, normalize(o)) for o in opts) and any(re.search(NO, normalize(o)) for o in opts):
                return _yes_no_option(opts, bool(backed) and not missing)
            level = ("advanced" if backed and not missing and all(v >= 3 for v in yrs.values()) else
                     "intermediate" if backed and not missing else
                     "basic" if backed or any(self.equivalent(k) for k in missing) else "none")
            order = [l for l, _ in LEVELS]
            for lvl in order[order.index(level):]:              # si no existe esa opción, la inmediatamente menor
                pat = dict(LEVELS)[lvl]
                for o in opts:
                    if re.search(pat, normalize(o)):
                        return o
            return None

        parts = []
        for k in backed:
            name = tax.name(k)
            since = f" ({'since' if en else 'desde'} {self.since_year(k)})" if k in yrs else ""
            fact = self.evidence_text(k)
            parts.append(f"{name}{since}: {fact}" if fact else f"{name}{since}")
        gaps = []
        for k in missing:
            eq = self.equivalent(k)
            name = tax.name(k)
            sk = self.profile.skill_map.get(k) or {}
            learning = sk.get("status") == "to_demonstrate" and sk.get("note")
            if en:
                gaps.append(f"I have no direct professional experience with {name}" +
                            (" (currently studying it: Master's in AI Development, in progress)" if learning else "") +
                            (f"; my equivalent experience is with {tax.name(eq)}" if eq else ""))
            else:
                gaps.append(f"No tengo experiencia profesional directa con {name}" +
                            (f", {sk['note'][0].lower()}{sk['note'][1:].rstrip('.')}" if learning else "") +
                            (f"; mi experiencia equivalente es con {tax.name(eq)}" if eq else ""))
        text = ""
        if parts:
            text = ("Yes. " if en else "Sí. ") + " · ".join(parts)
        if gaps:
            text = (text + (" " if text else "")) + ". ".join(gaps) + "."
        if missing and not backed and any(self.equivalent(k) for k in missing):
            eq = next(self.equivalent(k) for k in missing if self.equivalent(k))
            fact = self.evidence_text(eq)
            if fact:
                text += (" " + ("For example: " if en else "Por ejemplo: ") + fact)
        limit = int(field.get("maxlength") or 1000)
        return text[:limit].rsplit(" ", 1)[0] if len(text) > limit else text

    # ------------------------------------------------------------ entrada
    def answer(self, field: dict) -> str | None:
        label = field.get("question") or field.get("label") or ""
        if not label.strip():
            return None
        return self.from_bank(field, label) or self.from_evidence(field, label)


def _yes_no_option(opts: list[str], truth: bool) -> str | None:
    if not opts:
        return "Sí" if truth else "No"
    pat = YES if truth else NO
    for o in opts:
        if re.search(pat, normalize(o)):
            return o
    return None
