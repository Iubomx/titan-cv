"""Privacidad de la IA: sin datos de contacto por defecto, sin documentos de identidad nunca, y registro local."""
import json
from types import SimpleNamespace

import pytest

from cvtitan import llm, llm_privacy
from cvtitan.cli import main

PERSONAL = {"name": "Ana Pérez", "email": "ana@example.com", "phone": "+56 9 5555 0000", "location": "Lima, Perú",
            "linkedin": "linkedin.com/in/ana", "headline": "Analista de datos"}
CONTEXT = {"perfil": {"personal": dict(PERSONAL), "summary": "Resumen", "experience": [{"id": "e1"}]},
           "preferencias": {"salary_expectation": "PEN 6000", "national_id": "12.345.678-9", "birth_date": "1990-01-01"},
           "skills_respaldadas": ["Python"]}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("CVTITAN_LLM_SEND_CONTACT", raising=False)
    llm_privacy.set_audit_path(None)
    yield
    llm_privacy.set_audit_path(None)


def test_contact_data_is_removed_by_default_but_headline_stays():
    out = llm_privacy.scrub_contact(CONTEXT)
    assert out["perfil"]["personal"] == {"headline": "Analista de datos"}
    assert out["perfil"]["summary"] == "Resumen" and out["skills_respaldadas"] == ["Python"]


def test_scrub_does_not_mutate_the_original():
    llm_privacy.scrub_contact(CONTEXT)
    assert CONTEXT["perfil"]["personal"]["email"] == "ana@example.com"
    assert "national_id" in CONTEXT["preferencias"]


def test_identity_documents_are_removed_even_when_contact_is_allowed(monkeypatch):
    monkeypatch.setenv("CVTITAN_LLM_SEND_CONTACT", "1")
    out = llm_privacy.scrub_contact(CONTEXT)
    assert out["perfil"]["personal"]["email"] == "ana@example.com"          # el usuario lo permitió
    assert out["preferencias"] == {"salary_expectation": "PEN 6000"}         # esto nunca sale


def test_top_level_personal_block_is_scrubbed_too():
    out = llm_privacy.scrub_contact({"personal": dict(PERSONAL), "summary": "x"})
    assert out["personal"] == {"headline": "Analista de datos"}


def test_answer_fields_sends_no_contact_and_reports_sections(monkeypatch):
    seen = {}

    def fake_parse(system, user, schema, **kw):
        seen.update(user=user, **kw)
        return schema(answers=[])

    monkeypatch.setattr(llm, "_parse", fake_parse)
    llm.answer_fields([{"field_id": "f1", "pregunta": "¿Por qué?"}], CONTEXT)
    for secret in ("ana@example.com", "+56 9 5555 0000", "Ana Pérez", "12.345.678-9", "Lima"):
        assert secret not in seen["user"]
    assert seen["purpose"] == "answer_fields" and "campos" in seen["sent"] and "fuentes.perfil" in seen["sent"]


def test_cover_letter_scrubs_candidate_block(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "_parse", lambda system, user, schema, **kw: seen.update(user=user) or schema(text="ok"))
    llm.cover_letter({"title": "Dev", "company": "X", "skills": []}, {"personal": dict(PERSONAL), "summary": "s"})
    assert "ana@example.com" not in seen["user"] and "Analista de datos" in seen["user"]


def test_audit_record_has_metadata_only(tmp_path):
    path = tmp_path / "data" / "llm_audit.jsonl"
    llm_privacy.set_audit_path(path)
    usage = SimpleNamespace(input_tokens=120, output_tokens=40)
    llm_privacy.record("answer_fields", "claude-x", ["fuentes.perfil", "campos"], 900, usage)
    row = json.loads(path.read_text(encoding="utf-8").strip())
    assert row["purpose"] == "answer_fields" and row["input_tokens"] == 120 and row["send_contact"] is False
    assert set(row) == {"ts", "purpose", "model", "sent", "prompt_chars", "input_tokens", "output_tokens", "send_contact"}


def test_audit_disabled_or_unwritable_never_raises(tmp_path):
    llm_privacy.record("x", "m", [], 1)                      # sin ruta: no hace nada
    llm_privacy.set_audit_path(tmp_path)                     # una carpeta: no se puede abrir como archivo
    llm_privacy.record("x", "m", [], 1)


def test_read_skips_corrupt_lines_and_supports_tail(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text('{"purpose":"a"}\nnot json\n{"purpose":"b"}\n{"purpose":"c"}\n', encoding="utf-8")
    assert [r["purpose"] for r in llm_privacy.read(path)] == ["a", "b", "c"]
    assert [r["purpose"] for r in llm_privacy.read(path, tail=2)] == ["b", "c"]
    assert llm_privacy.read(tmp_path / "missing.jsonl") == []


def test_llmlog_command(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "llmlog"]) == 0
    assert "No AI requests" in capsys.readouterr().out
    llm_privacy.set_audit_path(tmp_path / "data" / "llm_audit.jsonl")
    llm_privacy.record("cover_letter", "claude-x", ["vacante"], 10)
    assert main(["--root", str(tmp_path), "llmlog"]) == 0
    out = capsys.readouterr().out
    assert "cover_letter" in out and "contact: no" in out and "never stored" in out
