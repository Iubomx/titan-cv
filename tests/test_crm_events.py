"""CRM: hitos del proceso (entrevistas, seguimientos) y agenda, con datos ficticios."""
from datetime import date

import pytest

from cvtitan.cli import main
from cvtitan.db import DB, PROCESS_EVENT_KINDS

TODAY = date(2026, 6, 10)


@pytest.fixture
def db(tmp_path):
    database = DB(tmp_path / "data" / "cvtitan.db")
    database.upsert("j1", company="Acme", title="Analista")
    database.upsert("j2", company="Globex", title="Dev")
    yield database
    database.close()


def test_add_and_list_events(db):
    first = db.add_process_event("j1", "interview", "2026-06-12", "Entrevista técnica")
    second = db.add_process_event("j1", "followup", "2026-06-20T10:00")
    assert second == first + 1
    rows = db.process_events("j1")
    assert [(r["kind"], r["due"], r["done"]) for r in rows] == [("interview", "2026-06-12", 0),
                                                                 ("followup", "2026-06-20", 0)]
    assert rows[0]["note"] == "Entrevista técnica"


@pytest.mark.parametrize("kind, due, error", [("llamada", "2026-06-12", ValueError), ("interview", "12/06/2026", ValueError),
                                              ("interview", "2026-13-40", ValueError)])
def test_invalid_kind_or_date_is_rejected(db, kind, due, error):
    with pytest.raises(error):
        db.add_process_event("j1", kind, due)
    assert db.process_events() == []


def test_unknown_job_is_rejected(db):
    with pytest.raises(KeyError):
        db.add_process_event("nope", "interview", "2026-06-12")


def test_agenda_includes_overdue_and_upcoming_but_not_done_or_far_events(db):
    overdue = db.add_process_event("j1", "followup", "2026-06-01")
    soon = db.add_process_event("j2", "interview", "2026-06-15")
    db.add_process_event("j1", "offer", "2026-09-01")                      # fuera de la ventana
    finished = db.add_process_event("j2", "test", "2026-06-11")
    assert db.complete_process_event(finished) is True
    agenda = db.agenda(days=14, today=TODAY)
    assert [r["id"] for r in agenda] == [overdue, soon]
    assert agenda[1]["company"] == "Globex" and agenda[1]["title"] == "Dev"


def test_complete_unknown_event_returns_false(db):
    assert db.complete_process_event(999) is False


def test_pending_only_filter(db):
    a = db.add_process_event("j1", "followup", "2026-06-12")
    db.add_process_event("j1", "interview", "2026-06-13")
    db.complete_process_event(a)
    assert [r["kind"] for r in db.process_events("j1", pending_only=True)] == ["interview"]


def test_deleting_an_application_removes_its_events(db):
    db.add_process_event("j1", "interview", "2026-06-12")
    db.add_process_event("j2", "interview", "2026-06-13")
    db.delete("j1")
    assert [r["job_id"] for r in db.process_events()] == ["j2"]


def test_kinds_are_the_documented_ones():
    assert PROCESS_EVENT_KINDS == ("interview", "followup", "test", "offer", "other")


def test_track_cli_event_agenda_done(tmp_path, capsys):
    root = str(tmp_path)
    DB(tmp_path / "data" / "cvtitan.db").upsert("j1", company="Acme", title="Analista")
    assert main(["--root", root, "track", "event", "j1", "--kind", "interview", "--on", "2099-01-01",
                 "--notes", "con RR. HH."]) == 0
    assert "Event #1 scheduled" in capsys.readouterr().out
    assert main(["--root", root, "track", "agenda", "--days", "36500"]) == 0
    out = capsys.readouterr().out
    assert "interview" in out and "Acme" in out and "con RR. HH." in out
    assert main(["--root", root, "track", "done", "1"]) == 0
    assert main(["--root", root, "track", "agenda", "--days", "36500"]) == 0
    assert "Nothing pending" in capsys.readouterr().out


def test_track_cli_errors_are_clean(tmp_path):
    root = str(tmp_path)
    DB(tmp_path / "data" / "cvtitan.db").upsert("j1")
    assert main(["--root", root, "track", "event", "j1"]) == 2                                   # faltan datos
    assert main(["--root", root, "track", "event", "nope", "--kind", "interview", "--on", "2099-01-01"]) == 2
    assert main(["--root", root, "track", "event", "j1", "--kind", "interview", "--on", "mañana"]) == 2
    assert main(["--root", root, "track", "done", "42"]) == 2
