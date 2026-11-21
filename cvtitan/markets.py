"""Mercados (países): lo que hasta ahora estaba cableado a Chile, ahora es un objeto configurable.

El mercado local del candidato se elige en `config/lines.yaml -> lines.A.market` (por defecto `chile`).
Plugins externos publican un `Market` con un entry point del grupo `cvtitan.markets`:

    [project.entry-points."cvtitan.markets"]
    colombia = "mi_paquete.mercados:COLOMBIA"      # un objeto `Market` (o una función que lo devuelva)
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Market:
    key: str
    country: str                                   # nombre para mensajes y ubicación de búsqueda
    home_regex: str                                # términos que identifican "mi región" (presencial/remoto regional)
    default_currency: str                          # moneda supuesta para montos grandes sin moneda
    no_currency_threshold: float = 100_000         # desde este monto, un sueldo sin moneda se asume en default_currency
    local_sources: tuple[str, ...] = field(default_factory=tuple)   # fuentes de la Línea A (ver apply/search.py)
    accept_language: str = "en"
    scan_label: str = ""                           # texto del centro de mando al escanear portales locales
    agent_label: str = ""

    @property
    def stage_name(self) -> str:
        return f"LINE A · {self.country.upper()}"


CHILE = Market(
    key="chile", country="Chile", home_regex=r"chile|santiago|latam|latin america", default_currency="CLP",
    local_sources=("getonboard", "computrabajo", "chiletrabajos", "indeed", "linkedin"),
    accept_language="es-CL,es;q=0.9", scan_label="Scanning Chilean job boards",
    agent_label="Chilean boards and mining career sites")

NO_GUESS = 10 ** 12          # un sueldo sin moneda NUNCA se asume en la moneda local (montos ambiguos con USD)


def _market(key: str, country: str, home_regex: str, currency: str, sources: tuple[str, ...], lang: str,
            threshold: float = NO_GUESS) -> Market:
    return Market(key=key, country=country, home_regex=home_regex, default_currency=currency,
                  no_currency_threshold=threshold, local_sources=sources, accept_language=lang,
                  scan_label=f"Scanning {country} job boards", agent_label=f"{country} boards and career sites")


LATAM = r"|latam|latin america"
# Portales del catálogo comprobados (config/job_boards.yaml). Chile conserva sus fuentes y umbral históricos.
BUILTIN: tuple[Market, ...] = (
    CHILE,
    _market("mexico", "Mexico", r"m[eé]xico|cdmx" + LATAM, "MXN", ("computrabajo_mx", "indeed_mx", "linkedin", "getonboard"), "es-MX,es;q=0.9"),
    _market("argentina", "Argentina", r"argentina|buenos aires" + LATAM, "ARS", ("computrabajo_ar", "indeed_ar", "linkedin", "getonboard"), "es-AR,es;q=0.9", 200_000),
    _market("colombia", "Colombia", r"colombia|bogot[aá]|medell[ií]n" + LATAM, "COP", ("computrabajo_co", "elempleo_co", "indeed_co", "linkedin", "getonboard"), "es-CO,es;q=0.9", 1_500_000),
    _market("peru", "Peru", r"per[uú]|lima" + LATAM, "PEN", ("computrabajo_pe", "indeed_pe", "linkedin", "getonboard"), "es-PE,es;q=0.9"),
    _market("uruguay", "Uruguay", r"uruguay|montevideo" + LATAM, "UYU", ("computrabajo_uy", "indeed_uy", "linkedin", "getonboard"), "es-UY,es;q=0.9"),
    _market("ecuador", "Ecuador", r"ecuador|quito|guayaquil" + LATAM, "USD", ("computrabajo_ec", "indeed_ec", "linkedin"), "es-EC,es;q=0.9"),
    _market("espana", "Spain", r"espa[nñ]a|spain|madrid|barcelona|emea|europe", "EUR", ("indeed_es", "linkedin"), "es-ES,es;q=0.9"),
    _market("brasil", "Brazil", r"brasil|brazil|s[aã]o paulo" + LATAM, "BRL", ("catho_br", "indeed_br", "linkedin"), "pt-BR,pt;q=0.9"),
    _market("usa", "United States", r"united states|usa|north america|americas", "USD", ("indeed_us", "linkedin"), "en-US,en;q=0.9"),
    _market("uk", "United Kingdom", r"united kingdom|\buk\b|england|london|emea|europe", "GBP", ("reed_uk", "indeed_uk", "linkedin"), "en-GB,en;q=0.9"),
    _market("canada", "Canada", r"canada|north america|americas", "CAD", ("jobbank_ca", "indeed_ca", "linkedin"), "en-CA,en;q=0.9"),
)
_BUILTIN_BY_KEY = {m.key: m for m in BUILTIN}
_MARKETS: dict[str, Market] = dict(_BUILTIN_BY_KEY)
_active: Market = CHILE
_plugins_loaded = False


def register(market: Market) -> Market:
    if market.key in _BUILTIN_BY_KEY and market is not _BUILTIN_BY_KEY[market.key]:
        warnings.warn(f"El mercado '{market.key}' es integrado; se ignora el plugin que intenta reemplazarlo.")
        return market
    _MARKETS[market.key] = market
    return market


def load_plugins() -> None:
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    from importlib.metadata import entry_points
    for ep in entry_points(group="cvtitan.markets"):
        try:
            obj = ep.load()
            register(obj() if callable(obj) and not isinstance(obj, Market) else obj)
        except Exception as exc:
            warnings.warn(f"No se pudo cargar el mercado '{ep.name}': {exc}")


def get(key: str) -> Market | None:
    load_plugins()
    return _MARKETS.get((key or "").strip().lower())


def active() -> Market:
    """Mercado local en uso (Chile por defecto)."""
    return _active


def configure(root: Path | None) -> Market:
    """Fija el mercado activo desde config/lines.yaml (lines.A.market). Un nombre desconocido deja Chile y avisa."""
    global _active
    key = "chile"
    if root:
        from .utils import load_yaml
        path = Path(root) / "config" / "lines.yaml"
        if path.exists():
            key = str((((load_yaml(path) or {}).get("lines") or {}).get("A") or {}).get("market") or "chile")
    market = get(key)
    if market is None:
        warnings.warn(f"Mercado desconocido '{key}': se usa Chile. Disponibles: {', '.join(sorted(_MARKETS))}.")
        market = CHILE
    _active = market
    return market
