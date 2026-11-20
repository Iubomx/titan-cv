"""Informe semanal: métricas reales del historial con fechas controladas (datos ficticios)."""
from datetime import date

import pytest

from cvtitan import weekly
from cvtitan.cli import main
from cvtitan.db import DB, STATUS_LABELS

TODAY = date(2026, 6, 10)


def _event(db, job_id, ts, message):
    db._conn.execute("INSERT INTO events (job_id, ts, kind, message) VALUES (?,?,?,?)", (job_id, ts, "status", message))
    db._conn.commit()


@pytest.fixture
def db(tmp_path):
    database = DB(tmp_path / "data" / "cvtitan.db")
    database.upsert("j1", company="Acme", title="Analista", status="screening", applied_at="2026-06-08T10:00:00")
    database.upsert("j2", company="Acme", title="Dev", status="applied", applied_at="2026-06-05T09:00:00")
    database.upsert("j3", company="Globex", title="Antigua", status="applied", applied_at="2026-05-20T09:00:00")
    database.upsert("j4", company="Initech", title="En cola")                        # sin enviar
    _event(database, "j1", "2026-06-10T10:00:00", STATUS_LABELS["screening"] + ": llamaron")
    yield database
    database.close()


def test_window_counts_only_sent_applications_inside_it(db):
    data = weekly.build(db, days=7, today=TODAY)
    assert (data["from"], data["to"], data["sent"]) == ("2026-06-04", "2026-06-10", 2)
    assert len(data["per_day"]) == 7 and data["per_day"]["2026-06-08"] == 1 and data["per_day"]["2026-06-05"] == 1
    assert data["by_status"] == {"applied": 1, "screening": 1}


def test_response_rate_and_time_to_first_response(db):
    data = weekly.build(db, days=7, today=TODAY)
    assert data["advanced"] == 1 and data["response_rate"] == 50.0
    assert data["median_days_to_response"] == 2.0


def test_no_response_event_means_no_median(db):
    db._conn.execute("DELETE FROM events")
    db._conn.commit()
    assert weekly.build(db, days=7, today=TODAY)["median_days_to_response"] is None


def test_top_companies_sorted_by_count_then_name(db):
    assert weekly.build(db, days=30, today=TODAY)["top_companies"] == [("Acme", 2), ("Globex", 1)]


def test_agenda_flows_into_the_report(db):
    db.add_process_event("j1", "interview", "2026-06-12", "técnica")
    db.add_process_event("j2", "followup", "2026-06-01")
    text = weekly.render(weekly.build(db, days=7, today=TODAY))
    assert "WEEKLY REPORT  2026-06-04 .. 2026-06-10" in text
    assert "2026-06-12 interview" in text and "OVERDUE followup" in text and "Response rate: 50.0%" in text


def test_empty_database_renders_without_errors(tmp_path):
    empty = DB(tmp_path / "e.db")
    data = weekly.build(empty, days=7, today=TODAY)
    assert data["sent"] == 0 and data["response_rate"] is None
    text = weekly.render(data)
    assert "n/a" in text and "Nothing scheduled" in text
    empty.close()


def test_urls_are_never_printed(db):
    db.upsert("j1", url="https://jobs.example.com/secret-path-42")
    assert "secret-path-42" not in weekly.render(weekly.build(db, days=7, today=TODAY))


def test_informe_semana_command(tmp_path, capsys):
    DB(tmp_path / "data" / "cvtitan.db").close()
    assert main(["--root", str(tmp_path), "informe", "--semana"]) == 0
    assert "WEEKLY REPORT" in capsys.readouterr().out
