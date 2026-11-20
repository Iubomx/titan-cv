"""Mercados: el país local ya no está cableado a Chile (datos ficticios, sin red)."""
import warnings

import pytest

from cvtitan import markets
from cvtitan.apply import intl_sources
from cvtitan.apply.search import vs_expectation
from cvtitan.market import _monthly_usd

PERU = markets.Market(key="peru", country="Peru", home_regex=r"peru|lima|latam", default_currency="PEN",
                      no_currency_threshold=10_000, local_sources=("computrabajo",), accept_language="es-PE,es;q=0.9")


@pytest.fixture(autouse=True)
def restore_markets(monkeypatch):
    monkeypatch.setattr(markets, "_MARKETS", dict(markets._MARKETS))
    monkeypatch.setattr(markets, "_active", markets.CHILE)
    monkeypatch.setattr(markets, "_plugins_loaded", True)


def _lines_yaml(tmp_path, market):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "lines.yaml").write_text(f"lines:\n  A:\n    market: {market}\n", encoding="utf-8")
    return tmp_path


def test_default_market_is_chile():
    m = markets.active()
    assert m.key == "chile" and m.stage_name == "LINE A · CHILE" and "getonboard" in m.local_sources


def test_configure_reads_market_from_lines_yaml(tmp_path):
    markets.register(PERU)
    assert markets.configure(_lines_yaml(tmp_path, "peru")).country == "Peru"
    assert markets.active() is PERU


def test_unknown_market_falls_back_to_chile_with_warning(tmp_path):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert markets.configure(_lines_yaml(tmp_path, "narnia")).key == "chile"
    assert caught and "narnia" in str(caught[0].message)


def test_plugin_cannot_replace_builtin_chile():
    fake = markets.Market(key="chile", country="X", home_regex="x", default_currency="XXX")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        markets.register(fake)
    assert caught and markets.get("chile") is markets.CHILE


def test_market_plugin_entry_point_is_loaded(monkeypatch):
    class EP:
        name = "peru"

        @staticmethod
        def load():
            return PERU

    monkeypatch.setattr(markets, "_plugins_loaded", False)
    monkeypatch.setattr("importlib.metadata.entry_points", lambda group=None: [EP])
    assert markets.get("peru") is PERU


def test_salary_without_currency_uses_market_default():
    assert vs_expectation({"salary_max": 1_500_000}, {"salary_gross": {"CLP": 1_000_000}}) == "ok"
    markets.register(PERU)
    markets._active = PERU
    assert vs_expectation({"salary_max": 12_000}, {"salary_gross": {"PEN": 10_000}}) == "ok"
    assert vs_expectation({"salary_max": 8_000}, {"salary_gross": {"PEN": 10_000}}) == "bajo (-20%)"


def test_monthly_usd_assumes_market_currency():
    markets._active = PERU
    assert _monthly_usd({"salary_min": 12_000}, {"PEN": 0.27}) == pytest.approx(3240.0)


def test_region_eligibility_accepts_home_country():
    assert intl_sources.region_eligibility(["Chile"]).startswith("ok")
    assert intl_sources.region_eligibility(["Peru"]).startswith("excluido")
    markets._active = PERU
    assert intl_sources.region_eligibility(["Peru"]).startswith("ok")
    assert intl_sources.region_eligibility(["Chile"]).startswith("excluido")
