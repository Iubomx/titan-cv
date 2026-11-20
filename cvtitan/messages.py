"""Catálogo de mensajes por idioma. Para agregar un idioma: añade un dict con las mismas claves que `es`.

Las claves que falten en un idioma se muestran en español (el idioma de referencia) y, si tampoco existen, la clave.
"""
from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "es": {
        "cli.label_error": "ERROR",
        "cli.label_warning": "AVISO",
        "profile.name_required": "personal.name es obligatorio.",
        "profile.item_no_id": "Un elemento de '{section}' no tiene id.",
        "profile.achievement_no_id": "Un logro de '{item}' no tiene id.",
        "profile.duplicate_ids": "IDs duplicados: {ids}",
        "profile.skill_bad_status": "Skill '{name}': status debe ser backed o to_demonstrate.",
        "profile.skill_missing_evidence": "Skill '{name}': evidencia inexistente {missing}.",
        "profile.backed_without_evidence": "Skill '{name}' está como backed pero no tiene evidencia.",
        "profile.project_not_completed": "Skill '{name}' se respalda en el proyecto '{ref}', que no está completado.",
        "profile.skill_undeclared": "'{ev_id}' usa la skill '{skill}', que no está declarada en skills.",
    },
    "en": {
        "cli.label_error": "ERROR",
        "cli.label_warning": "WARNING",
        "profile.name_required": "personal.name is required.",
        "profile.item_no_id": "An item in '{section}' has no id.",
        "profile.achievement_no_id": "An achievement of '{item}' has no id.",
        "profile.duplicate_ids": "Duplicate ids: {ids}",
        "profile.skill_bad_status": "Skill '{name}': status must be backed or to_demonstrate.",
        "profile.skill_missing_evidence": "Skill '{name}': evidence does not exist {missing}.",
        "profile.backed_without_evidence": "Skill '{name}' is marked backed but has no evidence.",
        "profile.project_not_completed": "Skill '{name}' is backed by project '{ref}', which is not completed.",
        "profile.skill_undeclared": "'{ev_id}' uses skill '{skill}', which is not declared in skills.",
    },
}
