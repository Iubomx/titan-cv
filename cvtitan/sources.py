"""Registro de fuentes de ofertas de la Línea B, ampliable con plugins.

Contrato de una fuente: `fetch(ctx: SourceContext) -> list[dict]`, donde cada oferta es un dict con las claves
`source, url, title, company, text, regions, salary` (ver `apply/intl_sources.py`). Se activa poniendo su nombre en
`config/lines.yaml -> lines.B.sources`.

Plugins externos: publica un paquete con un entry point en el grupo `cvtitan.sources`:

    [project.entry-points."cvtitan.sources"]
    mi_portal = "mi_paquete.fuentes:fetch"

Una fuente de un plugin nunca reemplaza a una integrada (se ignora con un aviso).
"""
from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .apply import intl_sources


@dataclass
class SourceContext:
    cache: Path                  # carpeta de caché diaria (data/cache)
    line: dict                   # configuración de la línea (config/lines.yaml -> lines.B)
    db_path: Path | None = None  # base de datos del workspace (para el escáner mundial de ATS)


Fetcher = Callable[[SourceContext], list[dict]]
_REGISTRY: dict[str, Fetcher] = {}
_BUILTIN: set[str] = set()
_plugins_loaded = False


def register(name: str, fn: Fetcher | None = None, *, builtin: bool = False):
    """Registra una fuente. Se puede usar como decorador: `@register("mi_portal")`."""
    def deco(f: Fetcher) -> Fetcher:
        if name in _BUILTIN and not builtin:
            warnings.warn(f"La fuente '{name}' es integrada; se ignora el plugin que intenta reemplazarla.")
            return f
        _REGISTRY[name] = f
        if builtin:
            _BUILTIN.add(name)
        return f
    return deco(fn) if fn is not None else deco


def _boards(ctx: SourceContext, kind: str) -> list[str]:
    boards = list(ctx.line.get(kind) or [])
    if ctx.line.get("world_scan", True):   # escáner mundial: las empresas que TITAN ya descubrió
        boards += intl_sources.known_boards(ctx.cache, ctx.db_path).get(kind, [])
    return boards


def _register_builtins() -> None:
    for name, fn in intl_sources.FETCHERS.items():
        register(name, lambda ctx, f=fn: f(ctx.cache), builtin=True)
    register("greenhouse", lambda ctx: intl_sources.greenhouse(ctx.cache, _boards(ctx, "greenhouse")), builtin=True)
    register("lever", lambda ctx: intl_sources.lever(ctx.cache, _boards(ctx, "lever")), builtin=True)


def load_plugins() -> None:
    """Carga las fuentes publicadas como entry points `cvtitan.sources` (una sola vez)."""
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    from importlib.metadata import entry_points
    for ep in entry_points(group="cvtitan.sources"):
        try:
            register(ep.name, ep.load())
        except Exception as exc:  # un plugin roto no debe tumbar la misión
            warnings.warn(f"No se pudo cargar la fuente '{ep.name}': {exc}")


def get(name: str) -> Fetcher | None:
    load_plugins()
    return _REGISTRY.get(name)


def names() -> list[str]:
    load_plugins()
    return sorted(_REGISTRY)


_register_builtins()
