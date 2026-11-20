"""Avisos de calidad del perfil y esquema JSON (datos ficticios)."""
import json
from datetime import date

import pytest

from cvtitan import i18n
from cvtitan.cli import main
from cvtitan.profile_checks import check
from cvtitan.profile_schema import json_schema

TODAY = date(2026, 6, 1)


@pytest.fixture(autouse=True)
def spanish(monkeypatch):
    monkeypatch.delenv("CVTITAN_LANG", raising=False)
    i18n.set_language("es")
    yield
    i18n.set_language(None)


def _exp(id_, start, end, achievements=()):
    return {"id": id_, "company": id_, "start": start, "end": end, "achievements": list(achievements)}


def test_clean_profile_has_no_warnings():
    data = {"personal": {"name": "Ana", "email": "ana@example.com"},
            "experience": [_exp("e1", "2020-01", "2022-12", [{"id": "a1", "text": "Reduje el tiempo 40%"}])],
            "skills": [{"name": "Python", "status": "backed", "evidence": ["a1", "p1"]}]}
    assert check(data, TODAY) == []


def test_invalid_email_and_unknown_key():
    out = check({"personal": {"name": "Ana", "email": "ana@@x"}, "experiance": []}, TODAY)
    assert any("correo" in w for w in out) and any("experiance" in w for w in out)


@pytest.mark.parametrize("bad", ["2021-13", "enero 2020", "20-1"])
def test_invalid_dates_are_reported_not_crashing(bad):
    out = check({"personal": {"name": "Ana"}, "experience": [_exp("e1", bad, "presente")]}, TODAY)
    assert any("no válida" in w for w in out)


def test_end_before_start():
    out = check({"personal": {"name": "Ana"}, "experience": [_exp("e1", "2022-05", "2021-01")]}, TODAY)
    assert any("anterior" in w for w in out)


def test_overlapping_experiences():
    data = {"personal": {"name": "Ana"},
            "experience": [_exp("e1", "2019-01", "2021-06"), _exp("e2", "2021-01", "presente")]}
    assert any("se solapan" in w and "e1" in w and "e2" in w for w in check(data, TODAY))


def test_back_to_back_experiences_do_not_overlap():
    data = {"personal": {"name": "Ana"},
            "experience": [_exp("e1", "2019-01", "2021-01"), _exp("e2", "2021-01", "presente")]}
    assert not any("se solapan" in w for w in check(data, TODAY))


def test_achievement_without_figures_and_single_evidence():
    data = {"personal": {"name": "Ana"},
            "experience": [_exp("e1", "2020-01", "2021-01", [{"id": "a1", "text": "Coordiné equipos"}])],
            "skills": [{"name": "SQL", "status": "backed", "evidence": ["a1"]},
                       {"name": "Go", "status": "to_demonstrate", "evidence": ["a1"]}]}
    out = check(data, TODAY)
    assert any("a1" in w and "cifras" in w for w in out)
    assert any("'SQL'" in w for w in out) and not any("'Go'" in w for w in out)


def test_warnings_follow_language():
    i18n.set_language("en")
    out = check({"personal": {"name": "Ana", "email": "bad"}}, TODAY)
    assert out == ["The email 'bad' does not look valid."]


def test_schema_lists_sections_and_status_enum():
    schema = json_schema()
    assert {"personal", "experience", "skills", "preferences"} <= set(schema["properties"])
    assert schema["$defs"]["Skill"]["properties"]["status"]["enum"] == ["backed", "to_demonstrate"]
    assert "personal" in schema["required"]


def test_schema_command_writes_valid_json(tmp_path):
    out = tmp_path / "profile.schema.json"
    assert main(["--root", str(tmp_path), "schema", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["title"] == "TITAN CV candidate profile"
