"""Registro de fuentes de la Línea B: integradas, plugins por entry point y escáner mundial (sin red)."""
import warnings
from pathlib import Path

import pytest

from cvtitan import sources
from cvtitan.apply import intl_sources


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    """Cada prueba parte del registro integrado y no carga plugins reales instalados."""
    monkeypatch.setattr(sources, "_REGISTRY", dict(sources._REGISTRY))
    monkeypatch.setattr(sources, "_plugins_loaded", True)


def _ctx(**line):
    return sources.SourceContext(Path("cache"), line, None)


def test_all_builtin_sources_are_registered():
    expected = set(intl_sources.FETCHERS) | {"greenhouse", "lever"}
    assert expected <= set(sources.names())


def test_register_decorator_adds_custom_source():
    @sources.register("mi_portal")
    def fetch(ctx):
        return [{"title": "Dev", "source": "mi_portal"}]

    assert sources.get("mi_portal")(_ctx()) == [{"title": "Dev", "source": "mi_portal"}]


def test_plugin_cannot_replace_builtin():
    original = sources.get("remotive")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sources.register("remotive", lambda ctx: ["hijacked"])
    assert caught and "integrada" in str(caught[0].message)
    assert sources.get("remotive") is original


def test_unknown_source_returns_none():
    assert sources.get("no_existe") is None


def test_builtin_wrapper_passes_cache_to_fetcher(monkeypatch):
    seen = []
    monkeypatch.setitem(intl_sources.FETCHERS, "remotive", lambda cache: seen.append(cache) or [])
    sources._register_builtins()          # reenlaza el wrapper con el fetcher simulado
    assert sources.get("remotive")(_ctx()) == []
    assert seen == [Path("cache")]


@pytest.mark.parametrize("world_scan, expected", [(True, ["a", "b"]), (False, ["a"])])
def test_greenhouse_merges_configured_and_discovered_boards(monkeypatch, world_scan, expected):
    called = {}
    monkeypatch.setattr(intl_sources, "known_boards", lambda cache, db: {"greenhouse": ["b"], "lever": []})
    monkeypatch.setattr(intl_sources, "greenhouse", lambda cache, boards: called.setdefault("boards", boards) and [])
    sources.get("greenhouse")(_ctx(greenhouse=["a"], world_scan=world_scan))
    assert called["boards"] == expected


def test_plugin_entry_points_are_loaded(monkeypatch):
    class EP:
        name = "plugin_portal"

        @staticmethod
        def load():
            return lambda ctx: [{"title": "From plugin"}]

    class BrokenEP:
        name = "broken"

        @staticmethod
        def load():
            raise ImportError("boom")

    monkeypatch.setattr(sources, "_plugins_loaded", False)
    monkeypatch.setattr("importlib.metadata.entry_points", lambda group=None: [EP, BrokenEP])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert sources.get("plugin_portal")(_ctx()) == [{"title": "From plugin"}]
    assert any("broken" in str(w.message) for w in caught)
    assert sources.get("broken") is None
