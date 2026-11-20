"""Historial de postulaciones (SQLite): estados, métricas y exportación, con datos ficticios."""
import csv
import io

import pytest

from cvtitan.db import DB


@pytest.fixture
def db(tmp_path):
    database = DB(tmp_path / "data" / "cvtitan.db")
    yield database
    database.close()


def _add(db, job_id, status, **fields):
    db.upsert(job_id, company="Acme", title="Analista", **fields)
    return db.set_status(job_id, status)


def test_upsert_creates_then_updates(db):
    row = db.upsert("j1", company="Acme", skills_backed=["Python"])
    assert row["status"] == "queued" and row["skills_backed"] == ["Python"]
    row = db.upsert("j1", title="Data Analyst")
    assert row["company"] == "Acme" and row["title"] == "Data Analyst"


def test_set_status_rejects_unknown_status(db):
    db.upsert("j1")
    with pytest.raises(ValueError):
        db.set_status("j1", "inventado")


def test_applied_sets_applied_at_once_and_logs_event(db):
    first = _add(db, "j1", "applied")
    assert first["applied_at"]
    again = db.set_status("j1", "applied")
    assert again["applied_at"] == first["applied_at"]
    assert [e["kind"] for e in db.events("j1")].count("status") >= 1


def test_list_filters_by_status_and_search(db):
    _add(db, "j1", "applied")
    db.upsert("j2", company="Globex", title="Dev")
    assert {r["job_id"] for r in db.list(status="applied")} == {"j1"}
    assert {r["job_id"] for r in db.list(search="glob")} == {"j2"}


def test_find_by_url(db):
    db.upsert("j1", url="https://example.com/job/1")
    assert db.find_by_url("https://example.com/job/1")["job_id"] == "j1"
    assert db.find_by_url("https://example.com/none") is None


def test_stats_response_rate_and_averages(db):
    _add(db, "a", "applied", score=40, country="Chile")
    _add(db, "b", "interview", score=80, country="Chile")
    _add(db, "c", "rejected", score=60, country="Peru")
    db.upsert("d")  # en cola: no cuenta como enviada
    s = db.stats()
    assert s["total"] == 4 and s["sent"] == 3
    assert s["response_rate"] == pytest.approx(33.3, abs=0.1)
    assert s["avg_score_advanced"] == 80.0
    assert s["avg_score_not_advanced"] == 50.0
    assert s["by_country"] == {"Chile": 2, "Peru": 1}


def test_stats_empty_database(db):
    s = db.stats()
    assert s["total"] == 0 and s["response_rate"] is None


def test_count_applied_today_by_platform(db):
    _add(db, "a", "applied", platform="getonbrd")
    _add(db, "b", "applied", platform="indeed")
    assert db.count_applied_today("getonbrd") == 1


def test_delete_removes_row_and_events(db):
    _add(db, "a", "applied")
    db.delete("a")
    assert db.get("a") is None and db.events("a") == []


def test_export_csv_has_header_and_rows(db):
    _add(db, "a", "applied", skills_backed=["Python", "SQL"])
    rows = list(csv.reader(io.StringIO(db.export_csv())))
    assert rows[0][-1] == "estado" and "data" not in rows[0]
    assert len(rows) == 2 and "Python, SQL" in rows[1]
