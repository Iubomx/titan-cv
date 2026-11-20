"""Vista previa y diff del CV adaptado contra el perfil (datos ficticios, sin red ni navegador)."""
import re
import shutil

import pytest

from cvtitan.cli import main
from cvtitan.cv_diff import diff_draft, preview_html, summarize, word_diff_html
from cvtitan.profile import Profile
from cvtitan.taxonomy import Taxonomy
from cvtitan.utils import Workspace, dump_yaml

REPO = Workspace.resolve(None)


@pytest.fixture(scope="module")
def profile():
    return Profile.load(REPO.example_profile_path, Taxonomy.load(REPO.taxonomy_path))


def _draft(bullets, summary=None):
    return {
        "personal": {"name": "Camila Rojas Fuentes", "email": "camila.rojas@example.com"}, "headline": "Analista",
        "summary": summary or {"text": "Analista de datos.", "source": "summary"},
        "skills": ["Python"], "projects": [], "education": [], "certifications": [], "languages": [],
        "experience": [{"source": "exp-minera-norte", "role": "Analista", "company": "Minera Ejemplo",
                        "location": "Antofagasta", "start": "2021-03", "end": "Presente", "bullets": bullets}],
    }


def test_identical_bullet_is_unchanged(profile):
    text = profile.evidence()["ach-reporte-automatico"]["text"]
    change = diff_draft(_draft([{"text": text, "source": "ach-reporte-automatico"}]), profile)[1]
    assert change["status"] == "unchanged" and change["added_numbers"] == []


def test_rewritten_bullet_with_same_numbers_is_edited_without_alerts(profile):
    original = profile.evidence()["ach-reporte-automatico"]["text"]
    rewritten = "Automaticé reportes con Python y SQL: de 3 horas a 20 minutos."
    assert {"3", "20"} <= set(re.findall(r"\d+", original))
    change = diff_draft(_draft([{"text": rewritten, "source": "ach-reporte-automatico"}]), profile)[1]
    assert change["status"] == "edited" and change["added_numbers"] == []


def test_new_number_is_flagged(profile):
    bullet = {"text": "Automaticé reportes y reduje 90% el tiempo.", "source": "ach-reporte-automatico"}
    change = diff_draft(_draft([bullet]), profile)[1]
    assert "90" in change["added_numbers"]


def test_unknown_source_is_flagged(profile):
    change = diff_draft(_draft([{"text": "Dirigí 50 personas", "source": "ach-inventado"}]), profile)[1]
    assert change["status"] == "unknown_source" and change["original"] is None


def test_summary_variant_source_is_resolved(profile):
    variant = profile.data["summary_variants"][0]
    draft = _draft([], summary={"text": variant["text"], "source": f"summary:{variant['id']}"})
    assert diff_draft(draft, profile)[0]["status"] == "unchanged"


def test_word_diff_marks_removed_and_added_and_escapes_html():
    html = word_diff_html("usé Python <b>", "usé SQL <i>")
    assert "<del>Python &lt;b&gt;</del>" in html and "<ins>SQL &lt;i&gt;</ins>" in html


def test_preview_escapes_untrusted_text_and_hides_panel_on_print(profile):
    bullet = {"text": "<script>alert(1)</script> 7 clientes", "source": "ach-inventado"}
    draft = _draft([bullet])
    html = preview_html(draft, diff_draft(draft, profile))
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "@media print{.review{display:none}}" in html and "fuente inexistente" in html


def test_summarize_counts(profile):
    text = profile.evidence()["ach-dashboard-kpi"]["text"]
    draft = _draft([{"text": text, "source": "ach-dashboard-kpi"}, {"text": "x 5", "source": "nope"}])
    s = summarize(diff_draft(draft, profile))
    assert s["blocks"] == 3 and s["unknown_source"] == 1 and s["with_new_numbers"] >= 1


def test_preview_command_writes_html(tmp_path, capsys, profile):
    (tmp_path / "candidate").mkdir()
    shutil.copy(REPO.example_profile_path, tmp_path / "candidate" / "profile.yaml")
    text = profile.evidence()["ach-etl-despacho"]["text"]
    dump_yaml(_draft([{"text": text, "source": "ach-etl-despacho"}]), tmp_path / "data" / "outputs" / "job1" / "cv_draft.yaml")
    assert main(["--root", str(tmp_path), "preview", "job1"]) == 0
    assert (tmp_path / "data" / "outputs" / "job1" / "cv_preview.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    assert "Preview:" in capsys.readouterr().out


def test_preview_without_draft_fails_cleanly(tmp_path):
    assert main(["--root", str(tmp_path), "preview", "nope"]) == 2
