"""Umbrales de puntaje configurables: los valores por defecto no cambian el comportamiento histórico."""
import warnings

import pytest

from cvtitan import scoring
from cvtitan.apply.search import adjusted_score
from cvtitan.evidence import _recommend
from cvtitan.line_b import score_line
from cvtitan.utils import Workspace, load_yaml

LINE = {"scoring": {"compatibility": 40, "eligibility": 25, "salary": 20, "experience": 15},
        "salary": {"min_monthly": 3000, "target_monthly": 4000}}


@pytest.fixture(autouse=True)
def restore_scoring(monkeypatch):
    monkeypatch.setattr(scoring, "_active", scoring.DEFAULT)


def test_shipped_template_equals_the_defaults():
    template = load_yaml(Workspace.resolve(None).root / "config" / "scoring.yaml")
    with warnings.catch_warnings():
        warnings.simplefilter("error")                       # ni claves desconocidas ni tipos inválidos
        assert scoring.from_dict(template) == scoring.DEFAULT


def test_historic_defaults():
    sc = scoring.DEFAULT
    assert (sc.min_skills, sc.non_tech_area_factor, sc.experience_floor) == (6, 0.6, 0.7)
    assert (sc.recommend_high, sc.recommend_mid, sc.recommend_low) == (70, 50, 30)


def test_from_dict_overrides_and_coerces_types():
    sc = scoring.from_dict({"min_skills": 4, "recommend_high": 80})
    assert sc.min_skills == 4 and isinstance(sc.min_skills, int) and sc.recommend_high == 80.0
    assert sc.recommend_mid == 50.0                          # lo demás queda por defecto


def test_unknown_and_invalid_values_are_ignored_with_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sc = scoring.from_dict({"nope": 1, "min_skills": "seis", "recommend_low": True})
    assert sc == scoring.DEFAULT and len(caught) == 3


def test_configure_reads_yaml_and_resets_without_file(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "scoring.yaml").write_text("recommend_mid: 60\n", encoding="utf-8")
    assert scoring.configure(tmp_path).recommend_mid == 60.0 and scoring.active().recommend_mid == 60.0
    assert scoring.configure(tmp_path / "otra") == scoring.DEFAULT


def test_adjusted_score_uses_min_skills_and_area_factor(monkeypatch):
    assert adjusted_score(80, 3, "") == 40.0
    monkeypatch.setattr(scoring, "_active", scoring.from_dict({"min_skills": 3, "non_tech_area_factor": 0.5}))
    assert adjusted_score(80, 3, "") == 80.0
    assert adjusted_score(80, 3, "sales") == 40.0


def test_recommendation_thresholds_move(monkeypatch):
    assert _recommend(65, 0.9).startswith("Postular con CV adaptado")
    monkeypatch.setattr(scoring, "_active", scoring.from_dict({"recommend_high": 60}))
    assert _recommend(65, 0.9).startswith("Postular: ajuste alto")


def test_line_b_points_are_configurable(monkeypatch):
    args = ({"score": 80}, 6, "ambiguo", None, True, (0, 0), LINE)
    assert score_line(*args)[1]["eligibility"] == 50 and score_line(*args)[1]["salary"] == 50
    monkeypatch.setattr(scoring, "_active", scoring.from_dict({"eligibility_ambiguous_points": 30,
                                                                "salary_unknown_points": 0}))
    parts = score_line(*args)[1]
    assert parts["eligibility"] == 30 and parts["salary"] == 0
