"""Catálogo de portales de empleo: datos validados, URL de búsqueda, patrones de oferta y mercados (sin red)."""
import warnings
from pathlib import Path

import httpx
import pytest

from cvtitan import fx, local_sources, markets, net
from cvtitan.apply.batch import clean_job_url, is_job_url
from cvtitan.apply.search import search_sources
from cvtitan.utils import PACKAGE_ROOT

CATALOG = PACKAGE_ROOT / "config" / "job_boards.yaml"


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(local_sources, "_REGISTRY", dict(local_sources._REGISTRY))
    monkeypatch.setattr(local_sources, "_loaded_catalogs", set())
    monkeypatch.setattr(local_sources, "_plugins_loaded", True)
    monkeypatch.setattr(markets, "_active", markets.CHILE)


def _names(prefix):
    return [n for n in local_sources.names() if n.startswith(prefix)]


def test_shipped_catalog_loads_without_a_single_warning(monkeypatch):
    """Se carga sobre un registro vacío: cualquier clave mal escrita, duplicado o regex inválida daría un aviso."""
    monkeypatch.setattr(local_sources, "_REGISTRY", {})
    monkeypatch.setattr(local_sources, "_BUILTIN", set())
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        added = local_sources.load_catalog(CATALOG)
    assert len(added) >= 80 and len(added) == len(set(added))


def test_catalog_coverage_by_family():
    assert len(_names("indeed")) >= 60 and len(_names("computrabajo")) >= 16
    assert {"elempleo_co", "catho_br", "reed_uk", "jobbank_ca"} <= set(local_sources.names())


def test_norway_is_not_parsed_as_the_boolean_false():
    """En YAML, `no:` a secas es falso: la clave de Noruega debe ir entre comillas y producir indeed_no."""
    assert "indeed_no" in local_sources.names() and not _names("indeed_False")
    assert local_sources.get("indeed_no").build_url("data analyst", "Oslo") == "https://no.indeed.com/jobs?q=data+analyst&l=Oslo"


@pytest.mark.parametrize("name, keyword, location, expected", [
    ("indeed_mx", "analista de datos", "Ciudad de México", "https://mx.indeed.com/jobs?q=analista+de+datos&l=Ciudad+de+M%C3%A9xico"),
    ("indeed_us", "data analyst", "Austin", "https://www.indeed.com/jobs?q=data+analyst&l=Austin"),
    ("computrabajo_co", "Analista de Datos", "", "https://co.computrabajo.com/trabajo-de-analista-de-datos"),
    ("reed_uk", "data analyst", "", "https://www.reed.co.uk/jobs/data-analyst-jobs"),
    ("jobbank_ca", "data analyst", "", "https://www.jobbank.gc.ca/jobsearch/jobsearch?searchstring=data+analyst"),
    ("catho_br", "Data Analyst", "", "https://www.catho.com.br/vagas/data-analyst/"),
    ("elempleo_co", "analista de datos", "", "https://www.elempleo.com/co/ofertas-empleo/?trabajo=analista+de+datos"),
])
def test_search_urls(name, keyword, location, expected):
    assert local_sources.get(name).build_url(keyword, location) == expected


def test_only_public_html_sources_are_read_without_a_browser():
    hosts = local_sources.http_hosts()
    assert {"pe.computrabajo.com", "www.reed.co.uk", "www.jobbank.gc.ca", "www.catho.com.br", "www.elempleo.com"} <= hosts
    assert not any("indeed.com" in h for h in hosts)               # Indeed bloquea clientes automáticos (403)


@pytest.mark.parametrize("url", [
    "https://www.reed.co.uk/jobs/data-analyst-transport/57557549",
    "https://www.jobbank.gc.ca/jobsearch/jobposting/50665928",
    "https://www.catho.com.br/vagas/business-data-analyst/39345066",
    "https://www.elempleo.com/co/ofertas-trabajo/analista-datos-1886799182",
    "https://mx.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-analista-en-ciudad-de-mexico-ABC123",
    "https://mx.indeed.com/viewjob?jk=0123456789abcdef",
])
def test_real_job_links_are_recognized(url):
    assert is_job_url(url)


@pytest.mark.parametrize("url", [
    "https://www.reed.co.uk/jobs/data-analyst-jobs",                  # listado, no una oferta
    "https://www.jobbank.gc.ca/login",
    "https://www.elempleo.com/co/ofertas-empleo/analista-de-datos",
    "https://www.catho.com.br/cadastro-candidato/",
])
def test_listing_and_other_pages_are_not_job_links(url):
    assert not is_job_url(url)


def test_job_bank_session_id_is_stripped_from_links():
    raw = "https://www.jobbank.gc.ca/jobsearch/jobposting/50665928;jsessionid=568D0B2DF0DBF4A9965D.jobsearch76?source=x"
    assert clean_job_url(raw) == "https://www.jobbank.gc.ca/jobsearch/jobposting/50665928"


def test_title_clean_removes_the_site_suffix_only_for_that_site():
    jb = "https://www.jobbank.gc.ca/jobsearch/jobposting/1"
    assert local_sources.clean_title(jb, "business data analyst - Toronto, ON - Job posting - Job Bank") == "business data analyst"
    assert local_sources.clean_title("https://www.reed.co.uk/jobs/x/1", "Data Analyst- Transport") == "Data Analyst- Transport"


def _write(tmp_path, text):
    path = tmp_path / "boards.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_invalid_entries_are_skipped_with_a_warning_and_good_ones_are_added(tmp_path):
    path = _write(tmp_path, """
boards:
  - {name: good_board, url: "https://jobs.example.com/q/{slug}", job_link: '^https://jobs\\.example\\.com/job/\\d+$', http: true}
  - {name: BadName, url: "https://x.example.com/{slug}"}
  - {name: no_https, url: "http://x.example.com/{slug}"}
  - {name: no_placeholder, url: "https://x.example.com/search"}
  - {name: bad_regex, url: "https://x.example.com/{slug}", job_link: "([unclosed"}
  - {name: bad_clean, url: "https://x.example.com/{slug}", title_clean: ["(["]}
  - {name: reed_uk, url: "https://dup.example.com/{slug}"}
""")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        added = local_sources.load_catalog(path)
    assert added == ["good_board"]
    assert len(caught) == 6
    assert local_sources.get("reed_uk").build_url("x", "").startswith("https://www.reed.co.uk")   # no se reemplaza
    assert "jobs.example.com" in local_sources.http_hosts()
    assert is_job_url("https://jobs.example.com/job/123")


def test_unreadable_or_empty_catalog_never_raises(tmp_path):
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        assert local_sources.load_catalog(tmp_path / "missing.yaml") == []
        assert local_sources.load_catalog(_write(tmp_path, "boards: [unclosed")) == []
    assert local_sources.load_catalog(_write(tmp_path, "")) == []


def test_workspace_catalog_is_loaded_once_and_never_for_the_package_file(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "job_boards.yaml").write_text(
        'boards:\n  - {name: my_portal, url: "https://mine.example.com/?q={keyword}", http: true}\n', encoding="utf-8")
    assert local_sources.load_workspace_catalog(tmp_path) == ["my_portal"]
    assert local_sources.load_workspace_catalog(tmp_path) == []                   # idempotente
    assert local_sources.load_workspace_catalog(PACKAGE_ROOT) == []               # el del paquete ya está cargado
    assert local_sources.get("my_portal").build_url("a b", "") == "https://mine.example.com/?q=a+b"


def test_every_builtin_market_points_to_registered_sources_and_known_currencies():
    assert len(markets.BUILTIN) >= 12
    for market in markets.BUILTIN:
        missing = [s for s in market.local_sources if local_sources.get(s) is None]
        assert not missing, f"{market.key}: fuentes inexistentes {missing}"
        assert market.default_currency in fx.DEFAULT_FX, f"{market.key}: falta {market.default_currency} en fx.DEFAULT_FX"
        assert market.country and market.accept_language and market.home_regex


def test_chile_keeps_its_historic_sources_and_threshold():
    assert markets.CHILE.local_sources == ("getonboard", "computrabajo", "chiletrabajos", "indeed", "linkedin")
    assert markets.CHILE.no_currency_threshold == 100_000


def test_currencies_that_collide_with_usd_amounts_are_never_guessed():
    for key in ("mexico", "peru", "brasil", "usa", "uk", "canada", "espana", "uruguay", "ecuador"):
        assert markets.get(key).no_currency_threshold >= 10 ** 9


def test_other_market_uses_its_own_sources_for_keyword_groups(monkeypatch):
    chile = search_sources([], ["computrabajo", "getonboard"], "Chile", groups=["datos"])
    assert any("cl.computrabajo.com" in u for u in chile) and any("getonbrd.com" in u for u in chile)
    monkeypatch.setattr(markets, "_active", markets.get("mexico"))
    mexico = search_sources([], ["computrabajo_mx", "indeed_mx"], "Mexico", groups=["datos"])
    assert mexico and all(("mx.computrabajo.com" in u or "mx.indeed.com" in u) for u in mexico)


def test_net_fetch_falls_back_to_urllib_when_httpx_cannot_connect(monkeypatch):
    class Boom:
        def get(self, *a, **k):
            raise httpx.ConnectTimeout("handshake colgado")

    class Resp:
        headers = type("H", (), {"get_content_charset": staticmethod(lambda: "utf-8")})()

        def read(self):
            return b"<html>ok</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(net, "_get_client", lambda: Boom())
    monkeypatch.setattr(net.urllib.request, "urlopen", lambda req, timeout=None: Resp())
    assert net.fetch("https://example.com/") == (b"<html>ok</html>", "utf-8")


def test_catalog_file_exists_and_documents_its_fields():
    text = Path(CATALOG).read_text(encoding="utf-8")
    for field in ("job_link", "title_clean", "http", "verified"):
        assert field in text
