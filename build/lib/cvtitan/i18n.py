"""Traducción de mensajes de usuario: `t("clave", dato=...)`.

Idioma: `--lang es|en` (CLI), variable `CVTITAN_LANG`, o español por defecto (el comportamiento histórico).
La migración de mensajes al catálogo (`cvtitan/messages.py`) se hace por etapas; lo no migrado sigue como estaba.
"""
from __future__ import annotations

import os

from .messages import MESSAGES

DEFAULT_LANG = "es"
_lang: str | None = None


def available() -> list[str]:
    return sorted(MESSAGES)


def set_language(lang: str | None) -> str:
    """Fija el idioma (None = variable de entorno o español). Un idioma desconocido vuelve al español."""
    global _lang
    chosen = (lang or os.environ.get("CVTITAN_LANG") or DEFAULT_LANG).strip().lower().split("_")[0].split("-")[0]
    _lang = chosen if chosen in MESSAGES else DEFAULT_LANG
    return _lang


def current() -> str:
    return _lang or set_language(None)


def t(key: str, /, **kw) -> str:
    template = MESSAGES.get(current(), {}).get(key) or MESSAGES[DEFAULT_LANG].get(key) or key
    try:
        return template.format(**kw)
    except (KeyError, IndexError):
        return template
