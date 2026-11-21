"""Diccionario de cargos de TITAN CV (config/job_dictionary.json).

Fuente: titan_cv_job_dictionary.json entregado por el candidato (2026-11-18): 22 categorías de cargos con
prioridad P1/P2/P3, tecnologías y modificadores. Se usa para:
  - Línea A: grupos de búsqueda por categoría en los portales públicos de Chile (búsqueda en paralelo);
  - Líneas A y B: filtro de títulos (un título del diccionario siempre cuenta como «cargo en tus áreas»).
Una tecnología del diccionario es un TÉRMINO DE BÚSQUEDA, no prueba de experiencia: las respuestas de los
formularios siguen saliendo solo del perfil (ver apply/question_bank.py).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .utils import PACKAGE_ROOT, normalize

DICT_PATH = PACKAGE_ROOT / "config" / "job_dictionary.json"
# Reglas del candidato que el diccionario no puede saltarse.
NEVER = re.compile(r"\bjunior\b|\bjr\b|\btrainee\b|\bintern(ship)?\b")


@lru_cache(maxsize=4)
def load(path: str | None = None) -> dict:
    p = Path(path) if path else DICT_PATH
    if not p.exists():
        return {"roles": {}, "priority": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def categories(priorities: list[str] | tuple[str, ...] = ("P1", "P2"), data: dict | None = None) -> list[str]:
    data = data or load()
    out: list[str] = []
    for p in priorities:
        out += [c for c in data.get("priority", {}).get(p, []) if c not in out]
    return out


def titles(priorities=("P1", "P2"), data: dict | None = None, cats: list[str] | None = None) -> list[str]:
    """Cargos (sin duplicados, sin «junior»), en orden de prioridad."""
    data = data or load()
    seen, out = set(), []
    for cat in cats or categories(priorities, data):
        for t in data.get("roles", {}).get(cat, []):
            n = normalize(t)
            if n and n not in seen and not NEVER.search(n):
                seen.add(n)
                out.append(t)
    return out


def search_groups(priorities=("P1", "P2"), sources: list[str] | None = None,
                  data: dict | None = None) -> dict[str, dict]:
    """Grupos para config/search_keywords.yaml: uno por categoría (prefijo `dic_`)."""
    data = data or load()
    sources = sources or ["getonboard", "computrabajo", "chiletrabajos"]
    groups = {}
    for cat in categories(priorities, data):
        kws = [normalize(t) for t in titles(cats=[cat], data=data)]
        if kws:
            groups[f"dic_{cat}"] = {"description": f"Diccionario de cargos · {cat}", "sources": list(sources),
                                    "keywords": kws}
    return groups


def title_regex(priorities=("P1", "P2"), data: dict | None = None) -> str:
    """Expresión que reconoce cualquier cargo del diccionario dentro de un título normalizado."""
    parts = sorted({re.escape(normalize(t)) for t in titles(priorities, data)}, key=len, reverse=True)
    return r"(?<![a-z])(" + "|".join(parts) + r")(?![a-z])" if parts else r"(?!x)x"
