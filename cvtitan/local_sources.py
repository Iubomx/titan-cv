"""Registro de fuentes locales (Línea A): portales de empleo de tu país, ampliable con plugins.

Una fuente local sabe construir la URL de búsqueda de una palabra clave y declara qué dominios se pueden leer por
HTTP sin navegador. Las integradas son las de Chile; otro país se agrega con un plugin:

    [project.entry-points."cvtitan.local_sources"]
    mi_portal = "mi_paquete.portales:MI_PORTAL"      # un objeto `LocalSource` (o una función que lo devuelva)

y se activa poniendo su nombre en `Market.local_sources` (ver `cvtitan/markets.py`) o en `config/search_keywords.yaml`.
Una fuente de un plugin nunca reemplaza a una integrada.
"""
from __future__ import annotations

import re
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from .utils import PACKAGE_ROOT, slugify


@dataclass(frozen=True)
class LocalSource:
    name: str
    build_url: Callable[[str, str], str]            # (palabra clave, ubicación) -> URL de búsqueda
    http_hosts: frozenset[str] = frozenset()        # dominios que se leen sin navegador
    job_link: str | None = None                     # regex del enlace de UNA oferta (sin parámetros)
    label: str = ""
    country: str = ""
    title_clean: tuple[str, ...] = ()               # regex que se quitan del título de la página (sufijos del sitio)


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


def job_link_patterns() -> list[str]:
    """Expresiones que reconocen enlaces de oferta de los portales del catálogo (se suman a batch.JOB_LINK_PATTERNS)."""
    load_plugins()
    return [src.job_link for src in _REGISTRY.values() if src.job_link]


# ---------------------------------------------------------------- catálogo de portales (datos, no código)
NAME_RE = re.compile(r"^[a-z0-9_]+$")
_loaded_catalogs: set[str] = set()


def render_url(template: str, keyword: str, location: str = "") -> str:
    """Rellena {keyword}, {slug}, {location} y {location_slug} de una plantilla de búsqueda."""
    return (template.replace("{keyword}", quote_plus(keyword)).replace("{slug}", slugify(keyword, 60))
            .replace("{location}", quote_plus(location)).replace("{location_slug}", slugify(location, 60)))


def _entry_problem(name: str, template: str, job_link: str | None, title_clean: tuple[str, ...] = ()) -> str | None:
    if not NAME_RE.match(name or ""):
        return f"nombre inválido '{name}' (usa a-z, 0-9 y _)"
    if not str(template).startswith("https://"):
        return "la plantilla debe empezar por https://"
    if "{keyword}" not in template and "{slug}" not in template:
        return "la plantilla debe incluir {keyword} o {slug}"
    for pattern in ([job_link] if job_link else []) + list(title_clean):
        try:
            re.compile(pattern)
        except re.error as exc:
            return f"'{pattern}' no es una expresión regular válida ({exc})"
    return None


def _builder(template: str) -> Callable[[str, str], str]:
    def build(keyword: str, location: str) -> str:
        return render_url(template, keyword, location)
    return build


def _make(name: str, template: str, http: bool, job_link: str | None, label: str, country: str,
          title_clean: tuple[str, ...] = ()) -> LocalSource:
    host = urlparse(template.replace("{", "x").replace("}", "")).netloc.lower()
    return LocalSource(name, _builder(template), frozenset({host}) if http and host else frozenset(),
                       job_link, label, country, title_clean)


def load_catalog(path: Path) -> list[str]:
    """Registra los portales de un catálogo YAML (ver config/job_boards.yaml). Devuelve los nombres agregados.

    Una entrada inválida se omite con un aviso; nunca reemplaza a una fuente integrada ni a otra ya cargada."""
    import yaml
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        warnings.warn(f"No se pudo leer el catálogo de portales {path}: {exc}")
        return []
    entries: list[dict] = []
    for fam_name, fam in (data.get("families") or {}).items():
        for code, host in (fam.get("hosts") or {}).items():
            entries.append({"name": f"{fam_name}_{code}", "url": str(fam.get("url", "")).replace("{host}", str(host)),
                            "job_link": fam.get("job_link"), "http": bool(fam.get("http")),
                            "label": f"{fam.get('label', fam_name)} ({str(code).upper()})", "country": str(code).upper()})
    entries += [dict(e) for e in data.get("boards") or []]
    added: list[str] = []
    for e in entries:
        name, template, job_link = str(e.get("name", "")), str(e.get("url", "")), e.get("job_link")
        title_clean = tuple(str(x) for x in e.get("title_clean") or [])
        problem = _entry_problem(name, template, job_link, title_clean)
        if problem:
            warnings.warn(f"Catálogo {Path(path).name}: se omite '{name}': {problem}")
        elif name in _REGISTRY:
            warnings.warn(f"Catálogo {Path(path).name}: '{name}' ya existe; se omite.")
        else:
            register(_make(name, template, bool(e.get("http")), job_link, str(e.get("label", name)),
                           str(e.get("country", "")), title_clean))
            added.append(name)
    return added


def clean_title(url: str, title: str) -> str:
    """Quita del título los sufijos propios del sitio (campo `title_clean` del catálogo) según el dominio de `url`."""
    load_plugins()
    host = urlparse(url).netloc.lower()
    for source in _REGISTRY.values():
        if source.title_clean and host in source.http_hosts:
            for pattern in source.title_clean:
                title = re.sub(pattern, "", title).strip()
    return title


def load_workspace_catalog(root: Path) -> list[str]:
    """Suma el catálogo propio `<root>/config/job_boards.yaml` (si existe y no es el del paquete). Una vez por ruta."""
    path = (Path(root) / "config" / "job_boards.yaml").resolve()
    if not path.exists() or str(path) in _loaded_catalogs or path == (PACKAGE_ROOT / "config" / "job_boards.yaml").resolve():
        return []
    _loaded_catalogs.add(str(path))
    return load_catalog(path)


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
load_catalog(PACKAGE_ROOT / "config" / "job_boards.yaml")
