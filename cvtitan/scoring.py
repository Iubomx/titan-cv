"""Umbrales y puntos del puntaje de compatibilidad, configurables en `config/scoring.yaml`.

Los valores por defecto reproducen el comportamiento histórico. Cualquier clave de `config/scoring.yaml` que no
exista aquí se ignora con un aviso; un valor del tipo equivocado también (se mantiene el valor por defecto).
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, fields, replace
from pathlib import Path


@dataclass(frozen=True)
class Scoring:
    # Línea A: cobertura de skills
    min_skills: int = 6                     # con menos skills detectadas, el % de cobertura no es confiable
    non_tech_area_factor: float = 0.6       # factor extra si el área de la vacante no es técnica
    # Compatibilidad (evidence.match)
    experience_floor: float = 0.7           # mínimo del factor si faltan años de experiencia
    recommend_high: float = 70.0
    recommend_high_required_coverage: float = 0.7
    recommend_mid: float = 50.0
    recommend_low: float = 30.0
    # Línea B: puntos por componente (0-100)
    eligibility_ok_points: float = 100.0
    eligibility_ambiguous_points: float = 50.0
    salary_target_points: float = 100.0
    salary_min_points: float = 70.0
    salary_below_points: float = 10.0
    salary_unknown_points: float = 50.0


DEFAULT = Scoring()
_active: Scoring = DEFAULT


def active() -> Scoring:
    return _active


def from_dict(data: dict | None) -> Scoring:
    """Scoring con los valores de `data` sobre los de por defecto (claves o tipos inválidos se ignoran)."""
    known = {f.name: f.type for f in fields(Scoring)}
    values = {}
    for key, value in (data or {}).items():
        if key not in known:
            warnings.warn(f"config/scoring.yaml: clave desconocida '{key}' (se ignora).")
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            warnings.warn(f"config/scoring.yaml: '{key}' debe ser un número (se mantiene el valor por defecto).")
        else:
            values[key] = type(getattr(DEFAULT, key))(value)
    return replace(DEFAULT, **values)


def configure(root: Path | None) -> Scoring:
    """Carga `<root>/config/scoring.yaml` (si existe) y la deja como configuración activa."""
    global _active
    _active = DEFAULT
    if root:
        path = Path(root) / "config" / "scoring.yaml"
        if path.exists():
            from .utils import load_yaml
            _active = from_dict(load_yaml(path))
    return _active
