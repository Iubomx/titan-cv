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

_MARKETS: dict[str, Market] = {CHILE.key: CHILE}
_active: Market = CHILE
_plugins_loaded = False


def register(market: Market) -> Market:
    if market.key in _MARKETS and market.key == CHILE.key and market is not CHILE:
        warnings.warn("El mercado 'chile' es integrado; se ignora el plugin que intenta reemplazarlo.")
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
