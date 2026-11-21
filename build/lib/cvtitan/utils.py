"""Utilidades compartidas: normalización de texto, YAML y rutas del workspace."""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parent.parent

_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def normalize(text: str | None) -> str:
    """Minúsculas y sin acentos, para comparar texto en español e inglés."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower())


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", normalize(text)).strip("-")
    return slug[:max_len].strip("-") or "item"


def numbers_in(text: str | None) -> set[str]:
    """Cifras presentes en un texto (para detectar métricas inventadas)."""
    return {n.replace(",", ".").rstrip(".") for n in _NUM.findall(text or "")}


def word_count(text: str | None) -> int:
    return len((text or "").split())


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def dump_yaml(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=100)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@dataclass
class Workspace:
    root: Path

    @classmethod
    def resolve(cls, root: str | os.PathLike | None = None) -> "Workspace":
        base = root or os.environ.get("CVTITAN_HOME") or PACKAGE_ROOT
        return cls(Path(base).resolve())

    @property
    def profile_path(self) -> Path:
        return self.root / "candidate" / "profile.yaml"

    @property
    def example_profile_path(self) -> Path:
        local = self.root / "candidate" / "profile.example.yaml"
        return local if local.exists() else PACKAGE_ROOT / "candidate" / "profile.example.yaml"

    @property
    def taxonomy_path(self) -> Path:
        local = self.root / "config" / "skills_taxonomy.yaml"
        return local if local.exists() else PACKAGE_ROOT / "config" / "skills_taxonomy.yaml"

    @property
    def db_path(self) -> Path:
        return self.root / "data" / "cvtitan.db"

    @property
    def answers_path(self) -> Path:
        """Respuestas que el candidato dio a preguntas de formularios, reutilizables."""
        return self.root / "candidate" / "answers.yaml"

    @property
    def documents_dir(self) -> Path:
        return self.root / "candidate" / "documents"

    @property
    def browser_profile(self) -> Path:
        return self.root / "data" / "browser-profile"

    @property
    def settings_path(self) -> Path:
        local = self.root / "config" / "settings.yaml"
        return local if local.exists() else PACKAGE_ROOT / "config" / "settings.yaml"

    @property
    def jobs_root(self) -> Path:
        return self.root / "data" / "jobs"

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_root / job_id

    def out_dir(self, job_id: str) -> Path:
        return self.root / "data" / "outputs" / job_id
