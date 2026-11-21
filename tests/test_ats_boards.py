"""Tableros de empresas en Workable, Recruitee y SmartRecruiters: lectura, formato común y descubrimiento (APIs simuladas)."""
import json
import sqlite3

import pytest

from cvtitan import sources
from cvtitan.apply import ats_boards as ab
from cvtitan.apply import intl_sources
from cvtitan.registry import ats_identity
from cvtitan.utils import PACKAGE_ROOT, load_yaml

LINE = {"keywords": ["engineer", "analyst"]}
COMMON_KEYS = {"source", "url", "apply_url", "title", "company", "text", "regions", "salary", "tags", "onsite", "ats"}


class FakeApi:
    """Reemplaza ab._get: responde JSON según un fragmento de la URL y cuenta las llamadas."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, *a, **k):
        self.calls.append(url)
        for fragment, payload in self.routes.items():
            if fragment in url:
                if isinstance(payload, Exception):
                    raise payload
                return json.dumps(payload).encode()
        raise AssertionError(f"URL inesperada: {url}")


def _install(monkeypatch, routes):
    api = FakeApi(routes)
    monkeypatch.setattr(ab, "_get", api)
    return api


WORKABLE = {"name": "Acme", "jobs": [
    {"title": "Data Engineer", "url": "https://apply.workable.com/j/AAA", "application_url": "https://apply.workable.com/j/AAA/apply",
     "telecommuting": True, "country": "France", "city": "Paris", "description": "<p>Build &amp; run pipelines</p>"},
    {"title": "Analyst", "url": "https://apply.workable.com/j/BBB", "telecommuting": False, "country": "Chile", "city": "Santiago",
     "description": "<p>On site</p>"},
    {"title": "", "url": "https://apply.workable.com/j/CCC"},                     # sin título: se ignora
    {"title": "No url"},                                                           # sin URL: se ignora
]}


def test_workable_offers_use_the_common_format_and_remote_text(tmp_path, monkeypatch):
    _install(monkeypatch, {"widget/accounts/acme": WORKABLE})
    remote, onsite = ab.workable(tmp_path, ["acme"])
    assert set(remote) == COMMON_KEYS and remote["ats"] == "workable" and remote["source"] == "Workable (acme)"
    assert remote["company"] == "Acme" and remote["apply_url"].endswith("/apply") and remote["text"] == "Build & run pipelines"
    assert remote["regions"] == ["Remote - France"] and remote["onsite"] is None
    assert onsite["regions"] is None and onsite["onsite"] == "Santiago, Chile" and onsite["apply_url"] == onsite["url"]


def test_unknown_or_broken_accounts_never_raise(tmp_path, monkeypatch):
    _install(monkeypatch, {"accounts/ghost": {"name": "ghost", "jobs": []}, "accounts/bad": OSError("caído"), "accounts/odd": []})
    assert ab.workable(tmp_path, ["ghost", "bad", "odd"]) == []


RECRUITEE = {"offers": [
    {"title": "Backend Engineer", "careers_url": "https://careers.x.com/o/be", "careers_apply_url": "https://careers.x.com/o/be/c/new",
     "remote": False, "city": "Amsterdam", "country": "Netherlands", "location": "Amsterdam, Netherlands", "company_name": "X BV",
     "description": "<p>Python</p>", "requirements": "<ul><li>SQL</li></ul>", "status": "published",
     "salary": {"min": 4000, "max": 6000, "currency": "EUR", "period": "month"}},
    {"title": "Data Analyst", "careers_url": "https://careers.x.com/o/da", "remote": True, "country": "Spain", "status": "published",
     "description": "", "requirements": "", "salary": {"min": None, "max": None, "currency": None, "period": None}},
    {"title": "Draft role", "careers_url": "https://careers.x.com/o/draft", "status": "draft"},
]}


def test_recruitee_merges_description_and_requirements_and_maps_salary(tmp_path, monkeypatch):
    _install(monkeypatch, {"x.recruitee.com/api/offers": RECRUITEE})
    onsite, remote = ab.recruitee(tmp_path, ["x"])              # el borrador no aparece
    assert onsite["company"] == "X BV" and "Python" in onsite["text"] and "SQL" in onsite["text"]
    assert onsite["salary"] == {"salary_min": 4000, "salary_max": 6000, "salary_currency": "EUR", "salary_period": "mes"}
    assert onsite["onsite"] == "Amsterdam, Netherlands" and remote["regions"] == ["Remote - Spain"] and remote["salary"] == {}
    assert onsite["ats"] == "recruitee"


def _posting(i, name, remote=False):
    return {"id": str(i), "name": name, "ref": f"https://api.smartrecruiters.com/v1/companies/Acme/postings/{i}",
            "company": {"name": "Acme Corp"}, "location": {"city": "Lima", "country": "pe", "remote": remote, "fullLocation": "Lima, Peru"}}


DETAIL = {"postingUrl": "https://jobs.smartrecruiters.com/Acme/1-data-engineer", "applyUrl": "https://jobs.smartrecruiters.com/Acme/1?oga=true",
          "jobAd": {"sections": {"jobDescription": {"text": "<p>Pipelines</p>"}, "qualifications": {"text": "<p>SQL</p>"}}}}


def test_smartrecruiters_only_downloads_details_for_matching_titles(tmp_path, monkeypatch):
    api = _install(monkeypatch, {"/postings?limit": {"content": [_posting(1, "Data Engineer"), _posting(2, "Chef de Cuisine"),
                                                               _posting(3, "Remote Analyst", remote=True)]},
                                 "/postings/1": DETAIL, "/postings/3": {"jobAd": {"sections": {}}}})
    offers = ab.smartrecruiters(tmp_path, ["Acme"], LINE)
    assert sorted(o["title"] for o in offers) == ["Data Engineer", "Remote Analyst"]
    assert not any("/postings/2" in c for c in api.calls)                          # «Chef» no pasa el filtro de cargo
    de = next(o for o in offers if o["title"] == "Data Engineer")
    assert de["url"].endswith("1-data-engineer") and " ".join(de["text"].split()) == "Pipelines SQL" and de["onsite"] == "Lima, Peru"
    assert next(o for o in offers if o["title"] == "Remote Analyst")["regions"] == ["Remote - PE"]


def test_smartrecruiters_paginates_and_caps_pages_and_details(tmp_path, monkeypatch):
    full_page = {"content": [_posting(i, f"Engineer {i}") for i in range(ab.SR_PAGE)]}
    api = _install(monkeypatch, {"/postings?limit": full_page, "/postings/": {"jobAd": {"sections": {}}}})
    offers = ab.smartrecruiters(tmp_path, ["Acme"], LINE)
    pages = [c for c in api.calls if "/postings?limit" in c]
    assert len(pages) == ab.SR_MAX_PAGES and len(offers) == ab.SR_MAX_DETAILS


def test_smartrecruiters_uses_the_daily_cache(tmp_path, monkeypatch):
    api = _install(monkeypatch, {"/postings?limit": {"content": [_posting(1, "Data Engineer")]}, "/postings/1": DETAIL})
    ab.smartrecruiters(tmp_path, ["Acme"], LINE)
    first = len(api.calls)
    ab.smartrecruiters(tmp_path, ["Acme"], LINE)
    assert len(api.calls) == first


def test_smartrecruiters_survives_failing_details(tmp_path, monkeypatch):
    _install(monkeypatch, {"/postings?limit": {"content": [_posting(1, "Data Engineer")]}, "/postings/1": OSError("timeout")})
    [offer] = ab.smartrecruiters(tmp_path, ["Acme"], LINE)
    assert offer["url"] == "https://jobs.smartrecruiters.com/Acme/1" and offer["text"] == ""


@pytest.mark.parametrize("url, expected", [
    ("https://apply.workable.com/huggingface/j/81B46579FE/", ("workable", "huggingface:81B46579FE")),
    ("https://apply.workable.com/j/81B46579FE", ("workable", "81B46579FE")),
    ("https://bunq.recruitee.com/o/copywriter-3", ("recruitee", "bunq:copywriter-3")),
    ("https://jobs.smartrecruiters.com/BoschGroup/744000162835320-quality-manager", ("smartrecruiters", "BoschGroup:744000162835320")),
])
def test_registry_recognizes_the_new_ats_urls(url, expected):
    assert ats_identity(url) == expected


def test_world_scan_discovers_companies_from_urls_already_seen(tmp_path):
    db = tmp_path / "cvtitan.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE vacancy_sources (url TEXT PRIMARY KEY, vacancy_id INTEGER, source TEXT, seen_at TEXT)")
    urls = ["https://apply.workable.com/huggingface/j/ABC123/", "https://bunq.recruitee.com/o/copywriter-3",
            "https://jobs.smartrecruiters.com/BoschGroup/744-x", "https://careers.smartrecruiters.com/Experian/99-y",
            "https://jobs.smartrecruiters.com/oneclick-ui/company/Foo", "https://boards.greenhouse.io/acme/jobs/1"]
    con.executemany("INSERT INTO vacancy_sources VALUES (?,?,?,?)", [(u, 1, "t", "2026-01-01") for u in urls])
    con.commit()
    con.close()
    found = intl_sources.known_boards(tmp_path / "cache", db)
    assert found["workable"] == ["huggingface"] and found["recruitee"] == ["bunq"]
    assert found["smartrecruiters"] == ["BoschGroup", "Experian"]          # «oneclick-ui» no es una empresa
    assert found["greenhouse"] == ["acme"]


def test_sources_are_registered_and_combine_configured_and_discovered_boards(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "_REGISTRY", dict(sources._REGISTRY))                # no contaminar otras pruebas
    for name in ("workable", "recruitee", "smartrecruiters"):
        assert sources.get(name) is not None
    seen = {}
    monkeypatch.setattr(ab, "workable", lambda cache, tokens: seen.setdefault("wk", tokens) and [])
    monkeypatch.setattr(intl_sources, "known_boards", lambda cache, db: {"workable": ["found"]})
    sources._REGISTRY["workable"] = sources._ats_source("workable", ab.workable)
    sources.get("workable")(sources.SourceContext(tmp_path, {"workable": ["mine"], "world_scan": True}, None))
    assert seen["wk"] == ["mine", "found"]
    seen.clear()
    sources.get("workable")(sources.SourceContext(tmp_path, {"workable": ["mine"], "world_scan": False}, None))
    assert seen["wk"] == ["mine"]


def test_shipped_line_b_config_lists_the_new_sources_as_human_step():
    line = load_yaml(PACKAGE_ROOT / "config" / "lines.yaml")["lines"]["B"]
    assert {"workable", "recruitee", "smartrecruiters"} <= set(line["sources"])
    assert {"workable", "recruitee", "smartrecruiters"} <= set(line["human_step_ats"])
    assert line["workable"] == [] and line["recruitee"] == [] and line["smartrecruiters"] == []
