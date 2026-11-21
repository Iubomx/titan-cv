"""Tipos de cambio para comparar sueldos (USD por unidad de moneda).

Por defecto se usa la tabla de `config/settings.yaml -> fx` (sin red). Con `fx_auto: true` se actualizan las monedas ISO
de esa tabla con tasas públicas del día (una consulta cada 24 h, en caché). La consulta es un GET genérico: no lleva
ningún dato tuyo. Si falla, se usa la caché vencida o, si no hay, la tabla. `UF` (unidad chilena) y `USD` no cambian.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_FX = {"USD": 1.0, "CLP": 1 / 950, "UF": 39000 / 950, "EUR": 1.08}   # supuestos: editables en settings.yaml
API_URL = "https://open.er-api.com/v6/latest/USD"
CACHE_HOURS = 24
FIXED = {"USD", "UF"}                       # no se actualizan desde la API


def _valid_rates(payload: object) -> dict[str, float]:
    """Tasas «unidades por USD» válidas de la respuesta de la API (descarta lo que no sea un número positivo)."""
    rates = payload.get("rates") if isinstance(payload, dict) else None
    if not isinstance(rates, dict):
        return {}
    return {str(cur).upper(): float(v) for cur, v in rates.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0}


def _default_fetch(url: str) -> bytes:
    from .net import fetch
    return fetch(url, {"User-Agent": "cv-titan/0.1 (fx rates)", "Accept": "application/json"}, 15)[0]


def live_rates(cache: Path, fetch: Callable[[str], bytes] | None = None, now: datetime | None = None) -> dict[str, float]:
    """Tasas «unidades por USD»: de la caché si tiene menos de 24 h, si no de la API; {} si no hay ninguna disponible."""
    now = now or datetime.now()
    stored: dict = {}
    if cache.exists():
        try:
            stored = json.loads(cache.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(stored["fetched_at"])
            if now - fetched < timedelta(hours=CACHE_HOURS) and _valid_rates(stored):
                return _valid_rates(stored)
        except (ValueError, KeyError, OSError, TypeError):
            stored = {}
    try:
        rates = _valid_rates(json.loads((fetch or _default_fetch)(API_URL)))
    except Exception:                                   # sin red, límite de la API, JSON inválido...
        return _valid_rates(stored)                     # caché vencida (si hay) antes que nada
    if rates:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"fetched_at": now.isoformat(timespec="seconds"), "rates": rates}), encoding="utf-8")
        except OSError:
            pass
    return rates or _valid_rates(stored)


def resolve(root: Path, settings: dict, fetch: Callable[[str], bytes] | None = None,
            now: datetime | None = None) -> dict[str, float]:
    """Tabla final de tipos de cambio (USD por unidad): defaults + settings, y tasas del día si `fx_auto: true`."""
    table = {**DEFAULT_FX, **(settings.get("fx") or {})}
    if settings.get("fx_auto") is not True:
        return table
    for cur, per_usd in live_rates(root / "data" / "cache" / "fx.json", fetch, now).items():
        if cur in table and cur not in FIXED:
            table[cur] = 1 / per_usd
    return table
