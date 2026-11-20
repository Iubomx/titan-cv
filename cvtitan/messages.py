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
        "profile.email_invalid": "El correo '{value}' no parece válido.",
        "profile.unknown_key": "Clave desconocida en el perfil: '{key}' (¿error de tipeo?).",
        "profile.date_invalid": "'{item}': fecha '{value}' no válida (usa AAAA-MM o 'presente').",
        "profile.date_order": "'{item}': la fecha de término es anterior a la de inicio.",
        "profile.achievement_no_figures": "El logro '{item}' no tiene cifras; si hay un dato real, agrégalo.",
        "profile.overlapping_experience": "Las experiencias '{a}' y '{b}' se solapan en fechas.",
        "profile.skill_single_evidence": "La skill '{name}' tiene una sola evidencia; una segunda la hace más defendible.",
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
        "profile.email_invalid": "The email '{value}' does not look valid.",
        "profile.unknown_key": "Unknown key in the profile: '{key}' (typo?).",
        "profile.date_invalid": "'{item}': date '{value}' is not valid (use YYYY-MM or 'present').",
        "profile.date_order": "'{item}': the end date is before the start date.",
        "profile.achievement_no_figures": "Achievement '{item}' has no figures; add a real number if you have one.",
        "profile.overlapping_experience": "Experiences '{a}' and '{b}' overlap in dates.",
        "profile.skill_single_evidence": "Skill '{name}' has a single piece of evidence; a second makes it easier to defend.",
    },
}
