"""Diccionario de preguntas + motor de evidencias: responde solo con hechos del perfil."""
import pytest

from cvtitan.apply.question_bank import QuestionBank
from cvtitan.profile import Profile
from cvtitan.taxonomy import Taxonomy
from cvtitan.utils import PACKAGE_ROOT, dump_yaml

BANK = {"questions": [
    {"id": "proyecto", "patterns": ["dispuest[oa] a trabajar .*proyecto"], "yesno": True},
    {"id": "correo", "patterns": ["envi(o|aste) (sus|tus) antecedentes"], "answer": {"es": "No; postulo por esta plataforma.", "en": "No."}},
    {"id": "anos", "patterns": ["^anos de experiencia$"], "answer": {"es": "{years_total}", "en": "{years_total}"}},
    {"id": "licencia", "patterns": ["licencia de conducir"], "note": "sin dato"},
]}
PROFILE = {
    "personal": {"name": "Ana Pérez"},
    "experience": [{"id": "exp1", "company": "Minera X", "role": "Analista", "start": "2020-01", "end": "presente",
                    "achievements": [{"id": "a1", "text": "Consultas SQL Server para KPIs de producción.", "skills": ["SQL"]},
                                     {"id": "a2", "text": "Dashboards de Power BI para el equipo de turno.", "skills": ["Power BI"]}]}],
    "skills": [{"name": "SQL", "status": "backed", "evidence": ["a1"]},
               {"name": "SQL Server", "status": "backed", "evidence": ["a1"]},
               {"name": "Power BI", "status": "backed", "evidence": ["a2"]},
               {"name": "LLMs", "status": "to_demonstrate", "note": "En formación (curso en línea)."}],
    "preferences": {"availability": "Inmediata"},
}


@pytest.fixture()
def qb(tmp_path):
    tax = Taxonomy.load(PACKAGE_ROOT / "config" / "skills_taxonomy.yaml")
    path = tmp_path / "profile.yaml"
    dump_yaml(PROFILE, path)
    prof = Profile.load(path, tax)
    bank = tmp_path / "question_bank.yaml"
    dump_yaml(BANK, bank)
    return QuestionBank(prof, bank)


def test_bank_patterns_yes_no_text_and_pending(qb):
    assert qb.answer({"type": "select", "label": "¿Estás dispuesto a trabajar por un proyecto?", "options": ["Sí", "No"]}) == "Sí"
    assert qb.answer({"type": "text", "label": "¿Envió sus antecedentes a rrhh@x.cl?"}).startswith("No; postulo")
    assert int(qb.answer({"type": "text", "label": "Años de experiencia"})) >= 6
    assert qb.answer({"type": "text", "label": "¿Tienes licencia de conducir?"}) is None      # sin dato: pendiente


def test_evidence_engine_backed_gap_and_equivalent(qb):
    text = qb.answer({"type": "textarea", "label": "¿Qué nivel de manejo tienes en SQL y BigQuery?"})
    assert text.startswith("Sí. SQL (desde 2020)") and "KPIs de producción" in text
    assert "No tengo experiencia profesional directa con BigQuery" in text and "SQL Server" in text
    gap = qb.answer({"type": "textarea", "label": "¿Has trabajado con Looker Studio?"})
    assert gap.startswith("No tengo experiencia profesional directa con Looker") and "Power BI" in gap
    learning = qb.answer({"type": "textarea", "label": "¿Tienes experiencia con IA generativa?"})
    assert "en formación (curso en línea)" in learning                                       # nunca se afirma experiencia


def test_evidence_engine_options_years_and_english(qb):
    assert qb.answer({"type": "select", "label": "Nivel de SQL", "options": ["Básico", "Intermedio", "Avanzado"]}) == "Avanzado"
    assert qb.answer({"type": "select", "label": "Do you have experience with Tableau?", "options": ["Yes", "No"]}) == "No"
    assert qb.answer({"type": "select", "label": "Experience with Power BI?", "options": ["Yes", "No"]}) == "Yes"
    years = qb.answer({"type": "number", "label": "¿Cuántos años de experiencia tienes con SQL o Power BI?"})
    assert int(years) >= 6
    en = qb.answer({"type": "textarea", "label": "Describe your experience with SQL"})
    assert en.startswith("Yes. SQL (since 2020)")


def test_job_dictionary_titles_groups_and_rules():
    from cvtitan import job_dictionary as jd
    data = {"roles": {"mining_dispatch": ["Mine Controller", "Despachador Mina"], "data_bi": ["Data Analyst", "Junior Data Analyst"],
                      "ux_ui_product": ["Product Designer"]},
            "priority": {"P1": ["mining_dispatch", "data_bi"], "P3": ["ux_ui_product"]}}
    assert jd.titles(("P1",), data) == ["Mine Controller", "Despachador Mina", "Data Analyst"]   # sin junior
    groups = jd.search_groups(("P1",), data=data)
    assert set(groups) == {"dic_mining_dispatch", "dic_data_bi"} and "despachador mina" in groups["dic_mining_dispatch"]["keywords"]
    import re
    rx = jd.title_regex(("P1",), data)
    assert re.search(rx, "senior mine controller") and not re.search(rx, "product designer")


def test_greenhouse_select_placeholder_is_not_a_question(tmp_path):
    from cvtitan.apply.answers import SavedAnswers, resolve
    tax = Taxonomy.load(PACKAGE_ROOT / "config" / "skills_taxonomy.yaml")
    path = tmp_path / "profile.yaml"
    dump_yaml({**PROFILE, "education": [{"id": "e1", "degree": "Ingeniería en Informática", "institution": "IACC", "year": 2026}]}, path)
    prof = Profile.load(path, tax)
    fields = [{"id": "f8", "type": "text", "label": "School*", "role": "combobox", "required": True, "value": ""},
              {"id": "f9", "type": "text", "label": "Select...", "role": "", "required": True, "value": ""}]
    values, questions = resolve(fields, prof, SavedAnswers(tmp_path / "a.yaml"), {}, {"url": "https://job-boards.greenhouse.io/x/jobs/1"})
    assert values == {"f8": "IACC"} and questions == []


def test_world_scan_filters_onsite_and_country_restricted_titles():
    from cvtitan.line_b import TITLE_PLACE
    assert TITLE_PLACE.search("Portuguese (Brazil) Content Operations Specialist -US (Remote)")
    assert TITLE_PLACE.search("Customer Success EMEA") and TITLE_PLACE.search("Senior Engineer (UK)")
    assert not TITLE_PLACE.search("Join us as Data Analyst") and not TITLE_PLACE.search("Python Developer - Remote LATAM")
    from cvtitan.apply import intl_sources
    assert intl_sources.region_eligibility(["Remote Canada"]).startswith("excluido")
    assert intl_sources.region_eligibility(["Remote - LATAM"]).startswith("ok")
