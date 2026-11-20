"""Perfil del candidato: fuente única de verdad y su índice de evidencias."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .i18n import t
from .taxonomy import Taxonomy
from .utils import load_yaml

VALID_STATUS = {"backed", "to_demonstrate"}
ONGOING = {"", "presente", "actual", "actualidad", "present", "current", "now", "none"}


def _parse_date(value, default: date | None = None) -> date | None:
    if value is None or str(value).strip().lower() in ONGOING:
        return default
    m = re.match(r"(\d{4})(?:[-/](\d{1,2}))?", str(value).strip())
    if not m:
        return default
    return date(int(m.group(1)), int(m.group(2) or 1), 1)


class Profile:
    def __init__(self, data: dict, taxonomy: Taxonomy):
        self.data = data
        self.tax = taxonomy
        self.skill_map: dict[str, dict] = {}
        for s in data.get("skills") or []:
            if not s.get("name"):
                continue
            key = taxonomy.key_for(s["name"])
            if s.get("aliases"):
                taxonomy.extend_aliases(key, s["aliases"])
            self.skill_map[key] = s
        self._evidence: dict[str, dict] | None = None
        self.path: Path | None = None

    def declarations(self) -> dict:
        """candidate/declarations.yaml (declaraciones legales confirmadas por el candidato)."""
        from .apply.legal import load_declarations
        base = self.path.parent if self.path else Path("candidate")
        return load_declarations(base / "declarations.yaml")

    @classmethod
    def load(cls, path: Path, taxonomy: Taxonomy) -> "Profile":
        if not path.exists():
            raise FileNotFoundError(
                f"No existe {path}. Ejecuta `cvtitan init` y completa tu perfil."
            )
        prof = cls(load_yaml(path), taxonomy)
        prof.path = path
        return prof

    # ------------------------------------------------------------------ evidencias
    def evidence(self) -> dict[str, dict]:
        """Índice id -> {kind, text, skills, parent, status} de todo lo verificable."""
        if self._evidence is not None:
            return self._evidence
        idx: dict[str, dict] = {}
        d = self.data
        for exp in d.get("experience") or []:
            idx[exp["id"]] = {
                "kind": "experience",
                "text": f"{exp.get('role', '')} {exp.get('company', '')}",
                "skills": exp.get("skills") or [],
                "parent": None,
            }
            for ach in exp.get("achievements") or []:
                idx[ach["id"]] = {
                    "kind": "achievement",
                    "text": ach.get("text", ""),
                    "skills": ach.get("skills") or [],
                    "parent": exp["id"],
                }
        for p in d.get("projects") or []:
            idx[p["id"]] = {
                "kind": "project",
                "text": f"{p.get('name', '')}. {p.get('description', '')}",
                "skills": p.get("skills") or [],
                "status": p.get("status", "completed"),
                "parent": None,
            }
        for section, kind in (("education", "education"), ("certifications", "certification")):
            for e in d.get(section) or []:
                label = e.get("degree") or e.get("name") or ""
                idx[e["id"]] = {
                    "kind": kind,
                    "text": f"{label} {e.get('institution') or e.get('issuer') or ''}",
                    "skills": e.get("skills") or [],
                    "parent": None,
                }
        self._evidence = idx
        return idx

    def evidence_skill_keys(self, ev_id: str) -> set[str]:
        e = self.evidence().get(ev_id)
        if not e:
            return set()
        keys = {self.tax.key_for(s, register=False) for s in e["skills"]}
        return keys | set(self.tax.find_in(e["text"]))

    # ------------------------------------------------------------------ skills
    def status(self, key: str) -> str | None:
        s = self.skill_map.get(key)
        return s.get("status") if s else None

    def is_backed(self, key: str) -> bool:
        s = self.skill_map.get(key)
        if not s or s.get("status") != "backed":
            return False
        ev = self.evidence()
        return any(i in ev for i in s.get("evidence") or [])

    def backed_keys(self) -> list[str]:
        return [k for k in self.skill_map if self.is_backed(k)]

    def summary_sources(self) -> dict[str, str]:
        out = {}
        if self.data.get("summary"):
            out["summary"] = self.data["summary"]
        for v in self.data.get("summary_variants") or []:
            out[f"summary:{v['id']}"] = v.get("text", "")
        return out

    # ------------------------------------------------------------------ métricas
    def years_experience(self, today: date | None = None) -> float:
        today = today or date.today()
        spans = []
        for exp in self.data.get("experience") or []:
            start = _parse_date(exp.get("start"))
            end = _parse_date(exp.get("end"), default=today)
            if start and end and end >= start:
                spans.append((start, end))
        spans.sort()
        merged: list[list[date]] = []
        for s, e in spans:
            if merged and s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        days = sum((e - s).days for s, e in merged)
        return round(days / 365.25, 1)

    # ------------------------------------------------------------------ validación
    def validate(self) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []
        d = self.data
        if not (d.get("personal") or {}).get("name"):
            errors.append(t("profile.name_required"))

        ids: list[str] = []
        for section in ("experience", "projects", "education", "certifications"):
            for item in d.get(section) or []:
                if not item.get("id"):
                    errors.append(t("profile.item_no_id", section=section))
                ids.append(item.get("id"))
                for ach in item.get("achievements") or []:
                    if not ach.get("id"):
                        errors.append(t("profile.achievement_no_id", item=item.get("id")))
                    ids.append(ach.get("id"))
        dupes = {i for i in ids if i and ids.count(i) > 1}
        if dupes:
            errors.append(t("profile.duplicate_ids", ids=", ".join(sorted(dupes))))

        ev = self.evidence()
        for s in self.skill_map.values():
            name = s["name"]
            status = s.get("status")
            if status not in VALID_STATUS:
                errors.append(t("profile.skill_bad_status", name=name))
                continue
            refs = s.get("evidence") or []
            missing = [r for r in refs if r not in ev]
            if missing:
                errors.append(t("profile.skill_missing_evidence", name=name, missing=missing))
            if status == "backed" and not refs:
                errors.append(t("profile.backed_without_evidence", name=name))
            for r in refs if status == "backed" else []:
                if ev.get(r, {}).get("kind") == "project" and ev[r].get("status") != "completed":
                    warnings.append(t("profile.project_not_completed", name=name, ref=r))

        declared = set(self.skill_map)
        for ev_id, e in ev.items():
            for sk in e["skills"]:
                if self.tax.key_for(sk, register=False) not in declared:
                    warnings.append(t("profile.skill_undeclared", ev_id=ev_id, skill=sk))
        from .profile_checks import check
        warnings.extend(check(self.data))
        return errors, warnings
