"""Web: filtro del embudo y paso de una oferta a postulación (URL real solo en el servidor; datos ficticios)."""
import pytest
from fastapi.testclient import TestClient

from cvtitan.db import DB
from cvtitan.funnel import write
from cvtitan.utils import Workspace
from cvtitan.web import insights
from cvtitan.web.app import create_app

URL_HIGH = "https://jobs.example.com/offers/high-1"
RECORDS = [
    {"line": "B", "stage": "scored", "tier": "high", "score": 92.0, "title": "Data Engineer", "company": "Acme",
     "source": "lever", "url": URL_HIGH, "pts_compatibility": 88.0},
    {"line": "B", "stage": "scored", "tier": "potential", "score": 46.0, "title": "Analyst", "company": "Globex",
     "source": "remotive", "url": "https://jobs.example.com/offers/pot-2", "reason_category": "score below threshold"},
    {"line": "B", "stage": "scored", "tier": "no", "score": 10.0, "title": "Sales", "company": "Initech",
     "source": "remoteok", "url": "https://jobs.example.com/offers/no-3", "reason_category": "off-target role"},
]


class FakeRunner:
    def __init__(self):
        self.commands = []

    def send(self, cmd, arg=None, **kw):
        self.commands.append((cmd, arg, kw))


@pytest.fixture
def env(tmp_path):
    write(RECORDS, tmp_path / "data" / "auto" / "runs" / "20261120-0800-funnel.csv", tmp_path / "data" / "auto" / "refs.json")
    app = create_app(Workspace(tmp_path), start_runner=False)
    app.state.runner = FakeRunner()
    return TestClient(app), app, {"X-Titan-Token": app.state.token}, tmp_path


def _code(client, tier):
    return client.get(f"/api/funnel?tier={tier}").json()["rows"][0]["code"]


def test_latest_funnel_tier_filter_and_code(tmp_path):
    write(RECORDS, tmp_path / "f-funnel.csv", tmp_path / "refs.json")
    allrows = insights.latest_funnel(tmp_path)
    assert all(r["code"].startswith("JOB-") and len(r["code"]) == 12 for r in allrows["rows"])
    only = insights.latest_funnel(tmp_path, tier="potential")
    assert [r["tier"] for r in only["rows"]] == ["potential"]
    assert only["tiers"] == allrows["tiers"] and only["total"] == 3          # los totales no dependen del filtro
    assert insights.latest_funnel(tmp_path, tier="manual")["rows"] == []


def test_funnel_endpoint_filter_and_limit_bounds(env):
    client, *_ = env
    assert [r["tier"] for r in client.get("/api/funnel?tier=high").json()["rows"]] == ["high"]
    assert len(client.get("/api/funnel?limit=1").json()["rows"]) == 1
    assert len(client.get("/api/funnel?limit=99999").json()["rows"]) == 3          # acotado a 200
    assert len(client.get("/api/funnel?limit=0").json()["rows"]) == 1              # mínimo 1


def test_queue_from_funnel_resolves_the_real_url_on_the_server(env):
    client, app, headers, tmp_path = env
    code = _code(client, "high")
    body = client.post(f"/api/funnel/{code}/queue", headers=headers).json()
    job_id = body["job_id"]
    row = DB(tmp_path / "data" / "cvtitan.db").get(job_id)
    assert row["url"] == URL_HIGH and row["status"] == "queued"
    assert app.state.runner.commands == [("start", job_id, {"force": False})]
    assert URL_HIGH not in client.get("/api/funnel").text                           # la página nunca ve la URL


def test_queueing_twice_does_not_start_the_robot_twice(env):
    client, app, headers, _ = env
    code = _code(client, "high")
    first = client.post(f"/api/funnel/{code}/queue", headers=headers).json()
    second = client.post(f"/api/funnel/{code}/queue", headers=headers).json()
    assert second == {"job_id": first["job_id"], "existing": True} and len(app.state.runner.commands) == 1


def test_already_applied_offer_is_a_conflict(env):
    client, _, headers, tmp_path = env
    db = DB(tmp_path / "data" / "cvtitan.db")
    db.upsert("old", url=URL_HIGH, status="applied", applied_at="2026-06-01T10:00:00")
    db.close()
    resp = client.post(f"/api/funnel/{_code(client, 'high')}/queue", headers=headers)
    assert resp.status_code == 409 and "Ya postulaste" in resp.json()["detail"]


@pytest.mark.parametrize("code, status", [("nope", 400), ("JOB-1234", 400), ("JOB-ZZZZZZZZ", 400), ("JOB-00000000", 404)])
def test_invalid_or_unknown_codes(env, code, status):
    client, _, headers, _ = env
    assert client.post(f"/api/funnel/{code}/queue", headers=headers).status_code == status


def test_queue_requires_the_session_token_and_an_active_robot(env):
    client, app, headers, _ = env
    code = _code(client, "high")
    assert client.post(f"/api/funnel/{code}/queue").status_code == 403
    app.state.runner = None
    assert client.post(f"/api/funnel/{code}/queue", headers=headers).status_code == 503


def test_page_has_the_filter_and_the_action_button(env):
    client, *_ = env
    page = client.get("/").text
    assert 'id="funnelFilter"' in page and "data-queue" in page and "esc(r.code)" in page
    assert "r.tier !== 'no'" in page                                                   # «No compatible» no ofrece Postular
