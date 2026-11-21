"""Fuentes locales (Línea A): las URLs integradas no cambian y los plugins pueden agregar portales (sin red)."""
import warnings

import pytest

from cvtitan import local_sources
from cvtitan.apply.search import HTTP_HOSTS, source_url
from cvtitan.local_sources import LocalSource


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    monkeypatch.setattr(local_sources, "_REGISTRY", dict(local_sources._REGISTRY))
    monkeypatch.setattr(local_sources, "_plugins_loaded", True)


@pytest.mark.parametrize("source, keyword, expected", [
    ("getonboard", "Analista de Datos", "https://www.getonbrd.com/jobs-analista-de-datos"),
    ("computrabajo", "Power BI", "https://cl.computrabajo.com/trabajo-de-power-bi"),
    ("chiletrabajos", "Python", "https://www.chiletrabajos.cl/trabajos/python"),
    ("indeed", "data analyst", "https://cl.indeed.com/jobs?q=data+analyst&l=Chile"),
])
def test_builtin_urls_are_unchanged(source, keyword, expected):
    assert source_url(source, keyword) == expected


def test_linkedin_builder_is_lazy_and_returns_a_search_url():
    assert "linkedin.com" in source_url("linkedin", "python", "Chile")


def test_unknown_source_lists_the_available_ones():
    with pytest.raises(ValueError, match="getonboard"):
        source_url("narnia", "x")


def test_builtin_http_hosts_are_kept_for_compatibility():
    assert {"www.getonbrd.com", "cl.computrabajo.com", "chiletrabajos.cl"} <= HTTP_HOSTS
    assert "cl.indeed.com" not in local_sources.http_hosts()       # indeed y linkedin requieren navegador


def test_registered_source_is_used_by_source_url_and_http_hosts():
    local_sources.register(LocalSource("trabajo_pe", lambda kw, loc: f"https://pe.example.com/jobs?q={kw}&city={loc}",
                                       frozenset({"pe.example.com"})))
    assert source_url("trabajo_pe", "python", "Lima") == "https://pe.example.com/jobs?q=python&city=Lima"
    assert "pe.example.com" in local_sources.http_hosts() and "trabajo_pe" in local_sources.names()


def test_plugin_cannot_replace_a_builtin_source():
    before = source_url("getonboard", "x")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        local_sources.register(LocalSource("getonboard", lambda kw, loc: "https://evil.example.com"))
    assert caught and "integrada" in str(caught[0].message)
    assert source_url("getonboard", "x") == before


def test_entry_point_plugins_are_loaded_and_broken_ones_ignored(monkeypatch):
    class Good:
        name = "plugin_portal"

        @staticmethod
        def load():
            return LocalSource("plugin_portal", lambda kw, loc: "https://plugin.example.com/" + kw)

    class Factory:
        name = "factory_portal"

        @staticmethod
        def load():
            return lambda: LocalSource("factory_portal", lambda kw, loc: "https://factory.example.com")

    class Broken:
        name = "broken"

        @staticmethod
        def load():
            raise ImportError("boom")

    monkeypatch.setattr(local_sources, "_plugins_loaded", False)
    monkeypatch.setattr("importlib.metadata.entry_points", lambda group=None: [Good, Factory, Broken])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert source_url("plugin_portal", "python") == "https://plugin.example.com/python"
    assert source_url("factory_portal", "x") == "https://factory.example.com"
    assert any("broken" in str(w.message) for w in caught) and local_sources.get("broken") is None
