"""import-cv asistido: estructura experiencia y sugiere evidencia sin respaldar nada (CV ficticio)."""
import pytest

from cvtitan.cli import main
from cvtitan.import_experience import structure_experience, suggest_evidence, to_month
from cvtitan.importer import draft_profile
from cvtitan.taxonomy import Taxonomy
from cvtitan.utils import Workspace, load_yaml

CV = """Juan Pérez Ejemplo
Analista de Datos
juan.perez@example.com
Experiencia
Analista de Datos - Minera Ejemplo
2021-03 - presente
- Automaticé reportes con Python y SQL, reduciendo de 3 horas a 20 minutos
- Diseñé dashboards en Power BI para 4 equipos
Analista Junior | Consultora Ejemplo
Enero 2019 - Febrero 2021
- Desarrollé macros en Excel y VBA para consolidar reportes
Educación
Ingeniería Civil Industrial, Universidad Ejemplo, 2018
"""


@pytest.fixture(scope="module")
def tax():
    return Taxonomy.load(Workspace.resolve(None).taxonomy_path)


@pytest.mark.parametrize("token, expected", [
    ("2021-03", "2021-03"), ("03/2021", "2021-03"), ("Marzo 2021", "2021-03"), ("sept. 2020", "2020-09"),
    ("2019", "2019"), ("Actual", "presente"), ("presente", "presente"), ("2021-13", ""), ("abc", ""),
])
def test_to_month(token, expected):
    assert to_month(token) == expected


def test_structure_two_entries_with_headers_dates_and_bullets(tax):
    lines = [ln for ln in CV.splitlines() if ln][4:-2]          # solo la sección de experiencia
    exps = structure_experience(lines, tax)
    assert [(e["role"], e["company"], e["start"], e["end"]) for e in exps] == [
        ("Analista de Datos", "Minera Ejemplo", "2021-03", "presente"),
        ("Analista Junior", "Consultora Ejemplo", "2019-01", "2021-02"),
    ]
    assert [len(e["achievements"]) for e in exps] == [2, 1]
    ids = [a["id"] for e in exps for a in e["achievements"]]
    assert ids == ["ach-1", "ach-2", "ach-3"] and len(set(ids)) == 3
    assert {"Python", "SQL"} <= set(exps[0]["achievements"][0]["skills"])


def test_header_line_is_not_duplicated_as_achievement(tax):
    lines = ["Analista - Acme", "2020-01 - 2021-01", "- Hice algo importante con 5 clientes"]
    exps = structure_experience(lines, tax)
    assert len(exps) == 1 and [a["text"] for a in exps[0]["achievements"]] == ["Hice algo importante con 5 clientes"]


def test_text_without_dates_yields_no_experience(tax):
    assert structure_experience(["Hice muchas cosas", "Trabajé en varias empresas"], tax) == []


def test_suggestions_map_skills_to_achievement_ids(tax):
    exps = structure_experience(["Dev - X", "2020 - 2021", "- Construí APIs con Python y SQL en 3 proyectos"], tax)
    sug = suggest_evidence(exps)
    assert sug["Python"] == ["ach-1"] and sug["SQL"] == ["ach-1"]


def test_draft_never_marks_a_skill_as_backed(tax):
    draft = draft_profile(CV, tax, source="cv.txt")
    assert len(draft["experience"]) == 2
    assert draft["detected_skills"] and all(s["status"] == "to_demonstrate" and s["evidence"] == []
                                            for s in draft["detected_skills"])
    python = next(s for s in draft["detected_skills"] if s["name"] == "Python")
    assert python["suggested_evidence"] == ["ach-1"]
    assert "sugerencias" in draft["_import"]["instructions"]


def test_import_cv_command_writes_draft(tmp_path, capsys):
    cv = tmp_path / "cv.txt"
    cv.write_text(CV, encoding="utf-8")
    assert main(["--root", str(tmp_path), "import-cv", str(cv)]) == 0
    draft = load_yaml(tmp_path / "candidate" / "profile.draft.yaml")
    assert len(draft["experience"]) == 2
    assert "Detected experiences: 2" in capsys.readouterr().out
