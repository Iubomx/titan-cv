"""Puntaje de la Línea B y normalización de sueldos: cubre cálculos que antes no tenían pruebas (datos ficticios)."""
import pytest

from cvtitan.line_b import score_line
from cvtitan.market import _monthly_usd

LINE = {
    "scoring": {"compatibility": 40, "eligibility": 25, "salary": 20, "experience": 15},
    "salary": {"min_monthly": 3000, "target_monthly": 4000},
}
M = {"score": 80}


def _score(**kw):
    args = dict(m=M, n_skills=6, elig="ok", usd=5000.0, years_ok=True, years=(0, 0), line=LINE)
    args.update(kw)
    return score_line(**args)


def test_score_line_best_case_is_weighted_mean():
    total, parts = _score()
    assert parts == {"compatibility": 80.0, "eligibility": 100, "salary": 100, "experience": 100}
    assert total == 92.0  # (80*40 + 100*25 + 100*20 + 100*15) / 100


@pytest.mark.parametrize("usd, expected", [(None, 50), (1000.0, 10), (3500.0, 70), (4000.0, 100)])
def test_salary_points_by_threshold(usd, expected):
    assert _score(usd=usd)[1]["salary"] == expected


def test_ambiguous_eligibility_gets_half_points():
    assert _score(elig="ambiguo")[1]["eligibility"] == 50


def test_experience_points_scale_with_years_when_below_requirement():
    assert _score(years_ok=False, years=(4, 2))[1]["experience"] == 50


def test_few_detected_skills_reduce_compatibility():
    assert _score(n_skills=3)[1]["compatibility"] == 40.0


def test_missing_weights_do_not_crash():
    total, _ = score_line(M, 6, "ok", 5000.0, True, (0, 0), {})
    assert total == 0.0


def test_monthly_usd_averages_range():
    assert _monthly_usd({"salary_min": 1000, "salary_max": 3000, "salary_currency": "USD"}, {"USD": 1.0}) == 2000.0


def test_monthly_usd_periods():
    fx = {"USD": 1.0}
    assert _monthly_usd({"salary_min": 120000, "salary_currency": "USD", "salary_period": "año"}, fx) == 10000.0
    assert _monthly_usd({"salary_min": 10, "salary_currency": "USD", "salary_period": "hora"}, fx) == 1600.0


def test_monthly_usd_unknown_currency_or_empty_is_none():
    assert _monthly_usd({"salary_min": 1000, "salary_currency": "XXX"}, {"USD": 1.0}) is None
    assert _monthly_usd({}, {"USD": 1.0}) is None


def test_monthly_usd_large_amount_without_currency_is_assumed_clp():
    assert _monthly_usd({"salary_min": 1_500_000}, {"CLP": 0.001}) == pytest.approx(1500.0)
