"""Vistas de la web: embudo con desglose del puntaje, resumen semanal y agenda (datos ficticios, sin navegador)."""
import pytest
from fastapi.testclient import TestClient

from cvtitan.db import DB
from cvtitan.funnel import write
from cvtitan.utils import Workspace
from cvtitan.web import insights
from cvtitan.web.app import create_app


def _records():
    return [
        {"line": "B", "stage": "scored", "tier": "no", "reason_category": "score below threshold", "reason": "puntaje 40 < 50",
         "score": 40.0, "title": "Dev Junior", "company": "Acme", "source": "remotive", "url": "https://example.com/a",
         "pts_compatibility": 40.0, "pts_eligibility": 100, "pts_salary": 0, "pts_experience": 50.0},
        {"line": "B", "stage": "scored", "tier": "high", "reason": "puntaje 92", "reason_category": "", "score": 92.0,
         "title": "Data Analyst", "company": "Globex", "source": "lever", "url": "https://example.com/b",
         "pts_compatibility": 80.0, "pts_eligibility": 100, "pts_salary": 100, "pts_experience": 100},
        {"line": "A", "stage": "scored", "tier": "potential", "reason": "ajuste 50 < 55", "reason_category": "score below threshold",
         "score": 50.0, "title": "Analista", "company": "Initech", "source": "getonboard", "url": "https://example.com/c"},
    ]


@pytest.fixture
def runs(tmp_path):
    folder = tmp_path / "data" / "auto" / "runs"
    write(_records(), folder / "20261120-0800-funnel.csv", tmp_path / "data" / "auto" / "refs.json")
    return folder


def test_no_funnel_yet_returns_an_empty_shape(tmp_path):
    data = insights.latest_funnel(tmp_path / "data" / "auto" / "runs")
    assert data["file"] is None and data["total"] == 0 and data["rows"] == []
    assert set(data["tiers"]) == {"high", "held", "manual", "potential", "review", "no"}


def test_latest_funnel_summarizes_tiers_and_reasons(runs):
    data = insights.latest_funnel(runs)
    assert data["file"] == "20261120-0800-funnel.csv" and data["total"] == 3
    assert data["tiers"]["high"] == 1 and data["tiers"]["no"] == 1 and data["tiers"]["potential"] == 1
    assert data["reasons"] == {"score below threshold": 1}              # solo cuenta los descartes («no»)


def test_rows_are_ordered_by_tier_then_score_and_carry_the_breakdown(runs):
    rows = insights.latest_funnel(runs)["rows"]
    assert [r["tier"] for r in rows] == ["high", "potential", "no"]
    assert rows[0]["points"] == {"compatibility": 80.0, "eligibility": 100.0, "salary": 100.0, "experience": 100.0}
    assert rows[1]["points"] == {}                                       # la Línea A no tiene desglose por componente
    assert rows[2]["points"]["salary"] == 0.0 and rows[2]["score"] == 40.0


def test_real_urls_never_reach_the_view(runs):
    text = str(insights.latest_funnel(runs))
    assert "https://example.com" not in text and "example.com/a" not in text and "#JOB-" in text


def test_picks_the_latest_file_and_respects_the_limit(runs):
    write([{"line": "A", "tier": "high", "title": f"T{i}", "score": i} for i in range(5)],
          runs / "20261121-0800-funnel.csv", runs.parent / "refs.json")
    data = insights.latest_funnel(runs, limit=3)
    assert data["file"].startswith("20261121") and data["total"] == 5 and len(data["rows"]) == 3


@pytest.fixture
def client(tmp_path, runs):
    db = DB(tmp_path / "data" / "cvtitan.db")
    db.upsert("j1", company="Acme", title="Analista", status="applied", applied_at="2026-06-08T10:00:00")
    db.add_process_event("j1", "interview", "2026-06-12", "técnica")
    db.close()
    return TestClient(create_app(Workspace(tmp_path), start_runner=False))


def test_funnel_endpoint(client):
    body = client.get("/api/funnel").json()
    assert body["total"] == 3 and body["tiers"]["high"] == 1 and body["rows"][0]["title"] == "Data Analyst"


def test_weekly_endpoint_shape_and_bounds(client):
    body = client.get("/api/weekly").json()
    assert {"from", "to", "sent", "advanced", "response_rate", "agenda", "per_day"} <= set(body)
    assert client.get("/api/weekly?days=9999").json()["days"] == 90
    assert client.get("/api/weekly?days=0").json()["days"] == 1


def test_page_has_the_new_panels_and_escapes_dynamic_text(client):
    page = client.get("/").text
    assert 'id="funnelCard"' in page and 'id="agendaCard"' in page and "loadInsights" in page
    assert "fbar" in page and "esc(r.title)" in page and "esc(e.note)" in page              # todo texto dinámico pasa por esc()
