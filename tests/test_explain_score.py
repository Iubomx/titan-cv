"""Explicabilidad: el desglose del puntaje se guarda por oferta y suma exactamente el puntaje total."""
import csv

import pytest

from cvtitan import line_b
from cvtitan.funnel import write
from cvtitan.line_b import COLUMNS, explain_score, score_line

LINE = {"scoring": {"compatibility": 40, "eligibility": 25, "salary": 20, "experience": 15},
        "salary": {"min_monthly": 3000, "target_monthly": 4000}}


def test_explanation_contributions_add_up_to_the_total():
    total, parts = score_line({"score": 80}, 6, "ok", 3500.0, False, (4, 2), LINE)
    rows = explain_score(parts, LINE)
    assert [r["component"] for r in rows] == ["compatibility", "eligibility", "salary", "experience"]
    assert sum(r["weight_pct"] for r in rows) == pytest.approx(100.0)
    assert sum(r["contribution"] for r in rows) == pytest.approx(total, abs=0.2)


def test_explanation_with_unnormalized_weights_and_no_weights():
    parts = {"compatibility": 50, "eligibility": 100}
    rows = explain_score(parts, {"scoring": {"compatibility": 1, "eligibility": 1}})
    assert [r["weight_pct"] for r in rows] == [50.0, 50.0] and [r["contribution"] for r in rows] == [25.0, 50.0]
    assert all(r["contribution"] == 0 for r in explain_score(parts, {}))


def test_decision_csv_columns_include_the_breakdown():
    for col in ("score_linea", "compatibilidad", "pts_elegibilidad", "pts_sueldo", "pts_experiencia"):
        assert col in COLUMNS
    assert hasattr(line_b, "explain_score")


def test_funnel_csv_keeps_zero_points_and_leaves_line_a_blank(tmp_path):
    records = [{"line": "B", "tier": "no", "title": "Dev", "pts_compatibility": 40.0, "pts_eligibility": 100,
                "pts_salary": 0, "pts_experience": 50.0, "score": 0, "url": "https://example.com/x"},
               {"line": "A", "tier": "high", "title": "Analista", "url": "https://example.com/y"}]
    write(records, tmp_path / "f.csv", tmp_path / "refs.json")
    rows = list(csv.DictReader((tmp_path / "f.csv").read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))
    assert rows[0]["pts_salary"] == "0" and rows[0]["pts_compatibility"] == "40.0" and rows[0]["score"] == "0"
    assert rows[1]["pts_salary"] == "" and rows[1]["pts_compatibility"] == ""
