"""Tipos de cambio automáticos y opcionales: sin red por defecto, caché de 24 h y respaldo ante fallos (red simulada)."""
import json
from datetime import datetime, timedelta

import pytest

from cvtitan import fx
from cvtitan.utils import Workspace, load_yaml

NOW = datetime(2026, 11, 20, 12, 0, 0)
PAYLOAD = json.dumps({"result": "success", "rates": {"USD": 1, "CLP": 1000.0, "EUR": 0.5, "PEN": 4.0}}).encode()


class Fetcher:
    def __init__(self, payload=PAYLOAD, error=None):
        self.payload, self.error, self.calls = payload, error, 0

    def __call__(self, url):
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload


def test_disabled_by_default_makes_no_request(tmp_path):
    f = Fetcher()
    table = fx.resolve(tmp_path, {"fx": {"CLP": 0.002}}, fetch=f, now=NOW)
    assert f.calls == 0 and table["CLP"] == 0.002 and table["USD"] == 1.0
    assert not (tmp_path / "data").exists()                       # tampoco escribe caché


def test_only_boolean_true_enables_live_rates(tmp_path):
    f = Fetcher()
    for value in ("true", 1, "yes", None):
        fx.resolve(tmp_path, {"fx_auto": value}, fetch=f, now=NOW)
    assert f.calls == 0


def test_live_rates_override_iso_currencies_only(tmp_path):
    table = fx.resolve(tmp_path, {"fx_auto": True, "fx": {"UF": 41.0}}, fetch=Fetcher(), now=NOW)
    assert table["CLP"] == pytest.approx(1 / 1000.0) and table["EUR"] == pytest.approx(2.0)
    assert table["USD"] == 1.0 and table["UF"] == 41.0            # USD y UF nunca se tocan
    assert "PEN" not in table                                     # solo monedas que ya estaban en la tabla


def test_cache_is_reused_for_24_hours_then_refreshed(tmp_path):
    f = Fetcher()
    settings = {"fx_auto": True}
    fx.resolve(tmp_path, settings, fetch=f, now=NOW)
    fx.resolve(tmp_path, settings, fetch=f, now=NOW + timedelta(hours=23))
    assert f.calls == 1
    fx.resolve(tmp_path, settings, fetch=f, now=NOW + timedelta(hours=25))
    assert f.calls == 2


def test_stale_cache_is_used_when_the_request_fails(tmp_path):
    settings = {"fx_auto": True}
    fx.resolve(tmp_path, settings, fetch=Fetcher(), now=NOW)
    table = fx.resolve(tmp_path, settings, fetch=Fetcher(error=OSError("sin red")), now=NOW + timedelta(days=3))
    assert table["CLP"] == pytest.approx(1 / 1000.0)


def test_table_is_used_when_there_is_no_cache_and_no_network(tmp_path):
    table = fx.resolve(tmp_path, {"fx_auto": True}, fetch=Fetcher(error=OSError("sin red")), now=NOW)
    assert table["CLP"] == fx.DEFAULT_FX["CLP"] and table["EUR"] == fx.DEFAULT_FX["EUR"]


@pytest.mark.parametrize("payload", [b"not json", b"[]", b'{"rates": 5}', b'{"rates": {"CLP": -3, "EUR": "x", "USD": true}}'])
def test_invalid_payloads_are_ignored(tmp_path, payload):
    table = fx.resolve(tmp_path, {"fx_auto": True}, fetch=Fetcher(payload=payload), now=NOW)
    assert table["CLP"] == fx.DEFAULT_FX["CLP"] and table["EUR"] == fx.DEFAULT_FX["EUR"]


def test_corrupt_cache_is_replaced(tmp_path):
    cache = tmp_path / "data" / "cache" / "fx.json"
    cache.parent.mkdir(parents=True)
    cache.write_text("{broken", encoding="utf-8")
    f = Fetcher()
    assert fx.resolve(tmp_path, {"fx_auto": True}, fetch=f, now=NOW)["CLP"] == pytest.approx(1 / 1000.0) and f.calls == 1


def test_market_keeps_exporting_default_fx_for_compatibility():
    from cvtitan.market import DEFAULT_FX
    assert DEFAULT_FX is fx.DEFAULT_FX


def test_shipped_settings_have_fx_auto_off():
    settings = load_yaml(Workspace.resolve(None).root / "config" / "settings.yaml")
    assert settings["fx_auto"] is False and {"USD", "CLP", "UF", "EUR"} <= set(settings["fx"])
