"""Web local: token anti-CSRF y rechazo de Host/Origin ajenos (sin navegador ni red)."""
import pytest
from fastapi.testclient import TestClient

from cvtitan.utils import Workspace
from cvtitan.web import guard
from cvtitan.web.app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(Workspace(tmp_path), start_runner=False)
    return TestClient(app), app.state.token


def test_host_parsing():
    assert guard.host_of("127.0.0.1:8765") == "127.0.0.1"
    assert guard.host_of("[::1]:8765") == "::1"
    assert guard.host_of("LOCALHOST:80") == "localhost"
    assert guard.host_of(None) == ""
    assert guard.host_ok("localhost:8765") and not guard.host_ok("evil.example.com") and not guard.host_ok(None)


def test_origin_rules():
    assert guard.origin_ok(None) and guard.origin_ok("http://127.0.0.1:8765")
    assert not guard.origin_ok("https://evil.example.com") and not guard.origin_ok("null")


def test_inject_token_adds_meta_once():
    html = guard.inject_token("<html><head><title>x</title></head><body></body></html>", "abc123")
    assert html.count('name="titan-token"') == 1 and 'content="abc123"' in html


def test_index_embeds_the_session_token(client):
    c, token = client
    page = c.get("/")
    assert page.status_code == 200 and f'content="{token}"' in page.text


def test_safe_requests_need_no_token(client):
    c, _ = client
    assert c.get("/api/stats").status_code == 200


@pytest.mark.parametrize("method, path", [("post", "/api/apply"), ("post", "/api/settings/apikey"),
                                          ("patch", "/api/applications/x"), ("delete", "/api/applications/x"),
                                          ("post", "/api/browser/open")])
def test_mutations_without_or_with_wrong_token_are_forbidden(client, method, path):
    c, _ = client
    assert c.request(method.upper(), path, json={}).status_code == 403
    assert c.request(method.upper(), path, json={}, headers={"X-Titan-Token": "nope"}).status_code == 403


def test_mutation_with_valid_token_passes_the_guard(client):
    c, token = client
    resp = c.delete("/api/applications/does-not-exist", headers={"X-Titan-Token": token})
    assert resp.status_code != 403


def test_foreign_origin_is_rejected_even_with_valid_token(client):
    c, token = client
    resp = c.delete("/api/applications/x", headers={"X-Titan-Token": token, "Origin": "https://evil.example.com"})
    assert resp.status_code == 403
    ok = c.delete("/api/applications/x", headers={"X-Titan-Token": token, "Origin": "http://127.0.0.1:8765"})
    assert ok.status_code != 403


def test_foreign_host_header_is_rejected_for_every_method(client):
    c, token = client
    assert c.get("/api/stats", headers={"Host": "evil.example.com"}).status_code == 403
    assert c.get("/", headers={"Host": "rebind.example.com:8765"}).status_code == 403


def test_each_app_instance_gets_its_own_token(tmp_path):
    a = create_app(Workspace(tmp_path), start_runner=False)
    b = create_app(Workspace(tmp_path), start_runner=False)
    assert a.state.token != b.state.token and len(a.state.token) >= 24
