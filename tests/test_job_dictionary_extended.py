"""Diccionario de cargos ampliado: 26 categorías en P3, sin cambiar lo que se busca por defecto."""
import json
import re

import pytest

from cvtitan import job_dictionary as jd
from cvtitan.utils import PACKAGE_ROOT, normalize

BASE = json.loads((PACKAGE_ROOT / "config" / "job_dictionary.json").read_text(encoding="utf-8"))
EXT = json.loads((PACKAGE_ROOT / "config" / "job_dictionary_extended.json").read_text(encoding="utf-8"))


def test_default_priorities_are_unchanged_so_default_searches_do_not_change():
    merged = jd.load()
    assert merged["priority"]["P1"] == BASE["priority"]["P1"]
    assert merged["priority"]["P2"] == BASE["priority"]["P2"]
    assert jd.categories(("P1", "P2")) == BASE["priority"]["P1"] + BASE["priority"]["P2"]


def test_extended_categories_are_new_and_land_in_exactly_one_priority_list():
    assert len(EXT["roles"]) == 26
    assert not set(EXT["roles"]) & set(BASE["roles"])                         # no choca con las categorías del candidato
    merged = jd.load()
    for category in EXT["roles"]:
        homes = [p for p, cats in merged["priority"].items() if category in cats]
        assert homes == ["P3"], f"{category}: {homes}"
    assert len(merged["roles"]) == len(BASE["roles"]) + 26


def test_base_dictionary_file_is_not_modified_by_the_merge():
    assert jd.load()["roles"]["data_bi"] == BASE["roles"]["data_bi"]
    assert "product_management" not in BASE["roles"]


@pytest.mark.parametrize("category", sorted(EXT["roles"]))
def test_every_extended_category_is_well_formed(category):
    titles = EXT["roles"][category]
    assert len(titles) >= 10
    assert all(isinstance(t, str) and t.strip() and t == t.strip() for t in titles)
    assert len({normalize(t) for t in titles}) == len(titles), "títulos repetidos dentro de la categoría"
    assert not [t for t in titles if jd.NEVER.search(normalize(t))], "el candidato no busca junior/trainee/intern"


def test_p3_exposes_hundreds_of_titles_in_three_languages():
    assert jd.load()["language"] == ["es", "en", "pt"]
    p3 = jd.titles(("P1", "P2", "P3"))
    assert len(p3) >= 700 and len(jd.titles(("P1", "P2"))) < len(p3)
    for sample in ("Product Manager", "Gerente de Marketing", "Engenheiro Civil", "Analista Financiero", "Enfermeiro"):
        assert sample in p3, sample


def test_title_regex_and_search_groups_cover_the_new_categories():
    rx = re.compile(jd.title_regex(("P3",)))
    assert rx.search(normalize("Gerente de Marketing Digital - Santiago"))
    assert rx.search(normalize("Senior Product Manager (Remote)"))
    groups = jd.search_groups(("P3",))
    assert "dic_product_management" in groups and "product manager" in groups["dic_product_management"]["keywords"]


def test_merge_base_wins_collisions_and_does_not_place_unknown_categories():
    base = {"roles": {"a": ["A1"]}, "priority": {"P1": ["a"]}, "language": ["es"], "version": "x"}
    ext = {"roles": {"a": ["OTHER"], "b": ["B1"]}, "priority": {"P3": ["a", "b", "ghost"]}, "language": ["es", "pt"]}
    out = jd.merge(base, ext)
    assert out["roles"] == {"a": ["A1"], "b": ["B1"]}                       # gana el base
    assert out["priority"] == {"P1": ["a"], "P3": ["b"]}                      # `a` ya estaba; `ghost` no existe
    assert out["language"] == ["es", "pt"] and out["version"] == "x"


def test_explicit_path_loads_only_that_file(tmp_path):
    path = tmp_path / "mine.json"
    path.write_text(json.dumps({"roles": {"x": ["Only Mine"]}, "priority": {"P1": ["x"]}}), encoding="utf-8")
    assert jd.load(str(path))["roles"] == {"x": ["Only Mine"]}
