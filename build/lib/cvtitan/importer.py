"""Importa un CV existente (PDF/DOCX/TXT) a un borrador de perfil para validación humana."""
from __future__ import annotations

import re
from pathlib import Path

from .import_experience import structure_experience, suggest_evidence
from .taxonomy import Taxonomy
from .utils import normalize, now_iso

SECTION_KEYS = {
    "summary": ["perfil", "resumen", "sobre mi", "acerca de", "summary", "profile", "about"],
    "experience": ["experiencia", "experience", "trayectoria", "employment"],
    "education": ["educacion", "formacion", "estudios", "education"],
    "skills": ["habilidades", "competencias", "conocimientos", "skills", "herramientas", "tecnologias"],
    "projects": ["proyectos", "projects", "portafolio", "portfolio"],
    "certifications": ["certificaciones", "certificados", "cursos", "certifications", "courses"],
    "languages": ["idiomas", "languages"],
}


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    if suffix == ".docx":
        from docx import Document
        doc = Document(str(path))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts)
    return path.read_text(encoding="utf-8", errors="replace")


def _section_of(line: str) -> str | None:
    n = normalize(line).strip(" :-•*#")
    if not n or len(n.split()) > 4:
        return None
    for section, keys in SECTION_KEYS.items():
        if any(n.startswith(k) for k in keys):
            return section
    return None


def draft_profile(text: str, taxonomy: Taxonomy, source: str) -> dict:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for line in lines:
        sec = _section_of(line)
        if sec:
            current = sec
            sections.setdefault(sec, [])
            continue
        sections.setdefault(current, []).append(line)

    experience = structure_experience(sections.get("experience", []), taxonomy)
    suggestions = suggest_evidence(experience)

    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    phone = re.search(r"\+?\d[\d\s()-]{7,}\d", text)
    linkedin = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+/?", text)
    github = re.search(r"(?:https?://)?(?:www\.)?github\.com/[\w-]+/?", text)

    detected = sorted(taxonomy.find_in(text), key=lambda k: taxonomy.name(k).lower())
    return {
        "_import": {
            "source": source,
            "imported_at": now_iso(),
            "instructions": "BORRADOR. Revisa cada dato con el candidato y trasládalo a candidate/profile.yaml. "
                            "Ninguna skill queda respaldada automáticamente: asigna `backed` solo con evidencia. "
                            "`experience` y `suggested_evidence` son sugerencias: corrige cargos, fechas y logros, "
                            "agrega cifras reales y copia al perfil solo lo que puedas defender.",
        },
        "personal": {
            "name": sections["header"][0] if sections["header"] else "",
            "headline": sections["header"][1] if len(sections["header"]) > 1 else "",
            "email": email.group(0) if email else "",
            "phone": phone.group(0).strip() if phone else "",
            "linkedin": linkedin.group(0) if linkedin else "",
            "github": github.group(0) if github else "",
        },
        "experience": experience,
        "detected_skills": [{"name": taxonomy.name(k), "status": "to_demonstrate", "evidence": [],
                             "suggested_evidence": suggestions.get(taxonomy.name(k), [])} for k in detected],
        "raw_sections": {k: v for k, v in sections.items() if v},
    }
