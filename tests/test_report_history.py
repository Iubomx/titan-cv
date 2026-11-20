"""Informe de historial: solo postulaciones enviadas, URLs enmascaradas y resolución de códigos (datos ficticios)."""
import pytest

from cvtitan.db import DB
from cvtitan.privacy import mask_url, ref, resolve_ref
from cvtitan.report import history_report

URL_A = "https://jobs.example.com/offers/secret-id-123"
URL_B = "https://www.example.org/careers/456"


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "data" / "cvtitan.db"
    db = DB(path)
    db.upsert("a", company="Acme", title="Analista", url=URL_A)
    db.set_status("a", "applied")
    db.upsert("b", company="Globex", title="Dev", url=URL_B)
    db.set_status("b", "rejected")
    db.upsert("c", company="Initech", title="Queued role", url="https://example.net/q")  # sin enviar
    db.close()
    return path


def test_history_lists_only_sent_applications(db_path):
    out = history_report(db_path, width=120)
    assert "Applications: 2 (all time)" in out
    assert "Acme" in out and "Globex" in out
    assert "Initech" not in out


def test_history_never_prints_full_urls(db_path):
    out = history_report(db_path, width=120)
    assert "secret-id-123" not in out and "/careers/456" not in out
    assert ref(URL_A) in out


def test_history_days_filter_keeps_recent(db_path):
    assert "Applications: 2 (last 7 days)" in history_report(db_path, days=7, width=120)


def test_history_empty_database(tmp_path):
    path = tmp_path / "data" / "cvtitan.db"
    DB(path).close()
    assert "Applications: 0" in history_report(path, width=120)


def test_mask_url_strips_www_and_path():
    masked = mask_url(URL_B)
    assert masked.startswith("example.org #JOB-") and "careers" not in masked


def test_resolve_ref_finds_url_from_history(db_path):
    assert resolve_ref(ref(URL_A), db_path) == [URL_A]
    assert resolve_ref(ref(URL_A).removeprefix("JOB-").lower(), db_path) == [URL_A]
    assert resolve_ref("JOB-00000000", db_path) == []
