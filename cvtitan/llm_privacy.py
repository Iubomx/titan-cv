"""Privacidad de la IA: minimiza lo que se envía a la API y deja un registro local de cada solicitud.

- `scrub_contact`: quita nombre, correo, teléfono, ubicación y enlaces del bloque `personal` antes de enviarlo.
  Solo se envían si activas `llm.send_contact: true` en config/settings.yaml (por defecto NO).
- `record`: añade una línea a `data/llm_audit.jsonl` por solicitud: fecha, función, modelo, secciones enviadas,
  tamaño y tokens. NUNCA guarda el contenido enviado ni la respuesta.
"""
from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path

CONTACT_KEYS = ("name", "email", "phone", "location", "city", "address", "linkedin", "github", "website", "portfolio")
SENSITIVE_PREFERENCE_KEYS = ("national_id", "birth_date", "rut", "dni", "passport", "tax_id", "ssn", "id_number")
_audit_path: Path | None = None


def send_contact_enabled() -> bool:
    return os.environ.get("CVTITAN_LLM_SEND_CONTACT") == "1"


def scrub_contact(context: dict) -> dict:
    """Copia de `context` sin datos sensibles.

    - Siempre: documentos de identidad y fecha de nacimiento dentro de `preferences`/`preferencias`.
    - Salvo `llm.send_contact: true`: nombre, correo, teléfono, ubicación y enlaces del bloque `personal`
      (también cuando viene anidado en `perfil` o `candidato`).
    """
    out = copy.deepcopy(context)
    holders = [out] + [v for v in out.values() if isinstance(v, dict)]
    for holder in holders:
        for prefs_key in ("preferences", "preferencias"):
            prefs = holder.get(prefs_key)
            if isinstance(prefs, dict):
                for key in SENSITIVE_PREFERENCE_KEYS:
                    prefs.pop(key, None)
        personal = holder.get("personal")
        if isinstance(personal, dict) and not send_contact_enabled():
            for key in CONTACT_KEYS:
                personal.pop(key, None)
    return out


def set_audit_path(path: Path | None) -> None:
    global _audit_path
    _audit_path = path


def record(purpose: str, model: str, sent: list[str], prompt_chars: int, usage=None) -> None:
    """Línea de auditoría (sin contenido). Un fallo al escribir nunca debe romper la postulación."""
    if _audit_path is None:
        return
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": purpose, "model": model, "sent": sent, "prompt_chars": prompt_chars,
        "input_tokens": getattr(usage, "input_tokens", None), "output_tokens": getattr(usage, "output_tokens", None),
        "send_contact": send_contact_enabled(),
    }
    try:
        _audit_path.parent.mkdir(parents=True, exist_ok=True)
        with _audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read(path: Path, tail: int | None = None) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows[-tail:] if tail else rows
