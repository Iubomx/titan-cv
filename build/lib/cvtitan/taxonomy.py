"""Taxonomía de habilidades: nombres canónicos + alias para detectar skills en texto libre."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .utils import load_yaml, normalize, slugify


@dataclass
class SkillDef:
    key: str
    name: str
    category: str = "other"
    aliases: list[str] = field(default_factory=list)


# Nombres que, sueltos en un texto, casi nunca son la tecnología ("R" de RR.HH., "go" en inglés).
AMBIGUOUS = {"go"}


def _pattern(aliases: list[str]) -> re.Pattern:
    alts = sorted({a for a in aliases if a and len(a) > 1 and a not in AMBIGUOUS}, key=len, reverse=True)
    if not alts:
        return re.compile(r"(?!x)x")                 # nunca coincide: solo se detecta por sus alias largos
    body = "|".join(re.escape(a) for a in alts)
    return re.compile(rf"(?<![a-z0-9])(?:{body})(?![a-z0-9])")


class Taxonomy:
    def __init__(self, skills: list[SkillDef] | None = None):
        self.skills: dict[str, SkillDef] = {}
        self._alias_index: dict[str, str] = {}
        self._patterns: dict[str, re.Pattern] | None = None
        for s in skills or []:
            self.add(s)

    @classmethod
    def load(cls, path: Path) -> "Taxonomy":
        data = load_yaml(path)
        skills = [
            SkillDef(
                key=k,
                name=v.get("name", k),
                category=v.get("category", "other"),
                aliases=list(v.get("aliases") or []),
            )
            for k, v in (data.get("skills") or {}).items()
        ]
        return cls(skills)

    def add(self, skill: SkillDef) -> None:
        names = [skill.name, *skill.aliases]
        skill.aliases = sorted({normalize(a).strip() for a in names if a and str(a).strip()})
        self.skills[skill.key] = skill
        for a in skill.aliases:
            self._alias_index.setdefault(a, skill.key)
        self._patterns = None

    def extend_aliases(self, key: str, aliases: list[str]) -> None:
        s = self.skills[key]
        self.add(SkillDef(s.key, s.name, s.category, s.aliases + list(aliases)))

    def key_for(self, name: str, register: bool = True) -> str:
        n = normalize(name).strip()
        if n in self._alias_index:
            return self._alias_index[n]
        key = slugify(name)
        if register and key not in self.skills:
            self.add(SkillDef(key=key, name=name, category="custom"))
        return key

    def name(self, key: str) -> str:
        return self.skills[key].name if key in self.skills else key

    def find_in(self, text: str | None) -> dict[str, int]:
        """Devuelve {skill_key: menciones} detectadas en el texto."""
        norm = normalize(text)
        if not norm:
            return {}
        if self._patterns is None:
            self._patterns = {k: _pattern(s.aliases) for k, s in self.skills.items()}
        found = {}
        for key, pat in self._patterns.items():
            count = len(pat.findall(norm))
            if count:
                found[key] = count
        return found
