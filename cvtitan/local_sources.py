"""Registro de fuentes locales (Línea A): portales de empleo de tu país, ampliable con plugins.

Una fuente local sabe construir la URL de búsqueda de una palabra clave y declara qué dominios se pueden leer por
HTTP sin navegador. Las integradas son las de Chile; otro país se agrega con un plugin:

    [project.entry-points."cvtitan.local_sources"]
    mi_portal = "mi_paquete.portales:MI_PORTAL"      # un objeto `LocalSource` (o una función que lo devuelva)

y se activa poniendo su nombre en `Market.local_sources` (ver `cvtitan/markets.py`) o en `config/search_keywords.yaml`.
Una fuente de un plugin nunca reemplaza a una integrada.
"""
from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote_plus

from .utils import slugify


@dataclass(frozen=True)
class LocalSource:
    name: str
    build_url: Callable[[str, str], str]            # (palabra clave, ubicación) -> URL de búsqueda
    http_hosts: frozenset[str] = frozenset()        # dominios que se leen sin navegador


_REGISTRY: dict[str, LocalSource] = {}
_BUILTIN: set[str] = set()
_plugins_loaded = False


def register(source: LocalSource, *, builtin: bool = False) -> LocalSource:
    if source.name in _BUILTIN and not builtin:
        warnings.warn(f"La fuente local '{source.name}' es integrada; se ignora el plugin que intenta reemplazarla.")
        return source
    _REGISTRY[source.name] = source
    if builtin:
        _BUILTIN.add(source.name)
    return source


def load_plugins() -> None:
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    from importlib.metadata import entry_points
    for ep in entry_points(group="cvtitan.local_sources"):
        try:
            obj = ep.load()
            register(obj() if callable(obj) and not isinstance(obj, LocalSource) else obj)
        except Exception as exc:                     # un plugin roto no debe tumbar la búsqueda
            warnings.warn(f"No se pudo cargar la fuente local '{ep.name}': {exc}")


def get(name: str) -> LocalSource | None:
    load_plugins()
    return _REGISTRY.get(name)


def names() -> list[str]:
    load_plugins()
    return sorted(_REGISTRY)


def http_hosts() -> set[str]:
    load_plugins()
    return {host for source in _REGISTRY.values() for host in source.http_hosts}


def _linkedin(keyword: str, location: str) -> str:
    from .apply.batch import linkedin_search_url     # importación diferida: evita ciclos con search.py
    return linkedin_search_url(keyword, location)


def _register_builtins() -> None:
    chile = (
        LocalSource("getonboard", lambda kw, loc: f"https://www.getonbrd.com/jobs-{slugify(kw, 60)}",
                    frozenset({"www.getonbrd.com", "getonbrd.com"})),
        LocalSource("computrabajo", lambda kw, loc: f"https://cl.computrabajo.com/trabajo-de-{slugify(kw, 60)}",
                    frozenset({"cl.computrabajo.com"})),
        LocalSource("chiletrabajos", lambda kw, loc: f"https://www.chiletrabajos.cl/trabajos/{slugify(kw, 60)}",
                    frozenset({"www.chiletrabajos.cl", "chiletrabajos.cl"})),
        LocalSource("indeed", lambda kw, loc: f"https://cl.indeed.com/jobs?q={quote_plus(kw)}&l={quote_plus(loc)}"),
        LocalSource("linkedin", _linkedin),
    )
    for source in chile:
        register(source, builtin=True)


_register_builtins()
