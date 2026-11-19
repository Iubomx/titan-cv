import shutil
from pathlib import Path

import pytest

from cvtitan import cv_writer, evidence, job_intel, recruiter
from cvtitan.db import DB
from cvtitan.cli import main
from cvtitan.profile import Profile
from cvtitan.taxonomy import Taxonomy
from cvtitan.utils import PACKAGE_ROOT, load_yaml

JOB_TEXT = (PACKAGE_ROOT / "examples" / "job_analista_datos.txt").read_text(encoding="utf-8")


@pytest.fixture
def tax():
    return Taxonomy.load(PACKAGE_ROOT / "config" / "skills_taxonomy.yaml")


@pytest.fixture
def profile(tax):
    return Profile.load(PACKAGE_ROOT / "candidate" / "profile.example.yaml", tax)


@pytest.fixture
def job(tax, profile):
    return job_intel.analyze(JOB_TEXT, tax, company="Minera Ejemplo", job_id="t1")


def test_taxonomy_aliases_and_word_boundaries(tax):
    found = tax.find_in("Manejo de PowerBI, T-SQL y PySpark. Experiencia en minería.")
    assert {"power_bi", "sql", "spark", "mining"} <= set(found)
    assert "r_lang" not in tax.find_in("Trabajo remoto en el rol")


def test_example_profile_is_valid(profile):
    errors, _ = profile.validate()
    assert errors == []
    assert profile.is_backed("python")
    assert not profile.is_backed("rag")


def test_job_sections(job):
    by_key = {s["key"]: s for s in job["skills"]}
    assert by_key["python"]["importance"] == "required"   # "(excluyente)" no es un encabezado
    assert by_key["azure"]["importance"] == "required"
    assert by_key["docker"]["importance"] == "preferred"
    assert by_key["rag"]["importance"] == "preferred"
    assert job["years_required"] == 4
    assert job["seniority"] == "senior"
    assert job["modality"] == "híbrido"
    assert all("seguro" not in r.lower() for r in job["requirements"])


def test_match_statuses(job, profile, tax):
    m = evidence.match(job, profile, tax)
    status = {r["key"]: r["status"] for r in m["rows"]}
    assert status["python"] == "backed"
    assert status["rag"] == "to_demonstrate"
    assert status["azure"] == "gap"
    assert 0 < m["score"] < 100


def test_draft_never_includes_unbacked_skills(job, profile, tax):
    m = evidence.match(job, profile, tax)
    draft = cv_writer.build_draft(job, m, profile, tax)
    assert "RAG" not in draft["skills"] and "Azure" not in draft["skills"]
    assert all(b["source"] for e in draft["experience"] for b in e["bullets"])
    assert recruiter.audit(draft, job, m, profile, tax)["passed"]


def test_audit_blocks_fabrication(job, profile, tax):
    m = evidence.match(job, profile, tax)
    draft = cv_writer.build_draft(job, m, profile, tax)
    bullet = draft["experience"][0]["bullets"][0]
    bullet["text"] += " Implementé RAG en Azure y ahorré 85% del costo."
    draft["skills"].append("Docker")
    codes = {f["code"] for f in recruiter.audit(draft, job, m, profile, tax)["findings"] if f["level"] == "error"}
    assert {"METRICA_NO_RESPALDADA", "SKILL_NO_RESPALDADA"} <= codes


def test_audit_requires_source(job, profile, tax):
    m = evidence.match(job, profile, tax)
    draft = cv_writer.build_draft(job, m, profile, tax)
    draft["experience"][0]["bullets"].append({"text": "Lideré un equipo.", "source": "inventado"})
    a = recruiter.audit(draft, job, m, profile, tax)
    assert not a["passed"]
    assert any(f["code"] == "SIN_FUENTE" for f in a["findings"])


def test_db_history_and_stats(tmp_path):
    db = DB(tmp_path / "h.db")
    db.upsert("a", company="A", country="Chile", modality="remoto", score=80)
    db.upsert("b", company="B", country="Perú", modality="presencial", score=40)
    db.set_status("a", "applied")
    db.set_status("b", "applied")
    db.set_status("a", "interview")
    s = db.stats()
    assert s["sent"] == 2 and s["response_rate"] == 50.0
    assert s["avg_score_advanced"] == 80.0
    assert s["by_country"] == {"Chile": 1, "Perú": 1}
    assert db.get("a")["applied_at"]
    assert "Entrevista" in db.export_csv()


def test_salary_and_country_heuristics(tax):
    text = ("Analista BI\nUbicación: Santiago, Chile\n"
            "Renta: $1.800.000 a $2.200.000 líquidos mensuales\nRequisitos\n- SQL")
    job = job_intel.analyze(text, tax, job_id="s1")
    assert job["country"] == "Chile"
    assert job["salary"]["salary_min"] == 1800000 and job["salary"]["salary_max"] == 2200000
    assert job["salary"]["salary_currency"] == "CLP" and job["salary"]["salary_period"] == "mes"


def test_jsonld_location_and_salary():
    raw = """<html><script type="application/ld+json">{"@type":"JobPosting","title":"Data Engineer",
      "hiringOrganization":{"name":"Acme"},"description":"<p>Python y SQL</p>",
      "jobLocation":{"address":{"addressLocality":"Lima","addressCountry":"PE"}},
      "baseSalary":{"currency":"USD","value":{"minValue":3000,"maxValue":4000,"unitText":"MONTH"}}}</script></html>"""
    meta = job_intel.parse_html(raw)
    assert meta["company"] == "Acme" and meta["city"] == "Lima"
    assert meta["salary_min"] == 3000 and meta["salary_currency"] == "USD" and meta["salary_period"] == "mes"


def test_llm_rewrites_are_gated_by_audit(job, profile, tax):
    from cvtitan.llm import CVRewrite, Rewrite
    m = evidence.match(job, profile, tax)
    draft = cv_writer.build_draft(job, m, profile, tax)
    first = draft["experience"][0]["bullets"][0]
    second = draft["experience"][0]["bullets"][1]
    rw = CVRewrite(headline="Analista de Datos Senior | Azure", summary=draft["summary"]["text"],
                   bullets=[Rewrite(source=first["source"], text=first["text"] + " Ahorro de 95%."),
                            Rewrite(source=second["source"], text="Mejoré " + second["text"][0].lower() + second["text"][1:])])
    draft, rejected = cv_writer.apply_rewrites(draft, rw, profile, tax)
    assert "headline" in rejected and first["source"] in rejected     # Azure y 95% no están respaldados
    assert draft["experience"][0]["bullets"][1]["text"].startswith("Mejoré")
    assert recruiter.audit(draft, job, m, profile, tax)["passed"]


def test_form_answer_rules(profile, tmp_path):
    from cvtitan.apply.answers import SavedAnswers, resolve
    fields = [
        {"id": "f1", "type": "text", "label": "Nombre *", "required": True, "value": ""},
        {"id": "f2", "type": "text", "label": "Apellidos", "required": True, "value": ""},
        {"id": "f3", "type": "email", "label": "Correo electrónico", "required": True, "value": ""},
        {"id": "f4", "type": "file", "label": "Adjunta tu CV", "required": True, "value": ""},
        {"id": "f5", "type": "select", "label": "Género", "required": False, "value": "",
         "options": ["Femenino", "Masculino", "Prefiero no decirlo"]},
        {"id": "f6", "type": "text", "label": "¿Cuántos años has trabajado con Kubernetes?", "required": True, "value": ""},
        {"id": "f7", "type": "text", "label": "Pretensión de renta", "required": True, "value": ""},
    ]
    saved = SavedAnswers(tmp_path / "answers.yaml")
    values, questions = resolve(fields, profile, saved, {"cv": "C:/cv.pdf"}, {"title": "X"})
    assert values["f1"] == "Camila" and values["f2"] == "Rojas Fuentes"
    assert values["f3"].endswith("@example.com") and values["f4"] == "C:/cv.pdf"
    assert values["f5"] == "Prefiero no decirlo"
    assert values["f7"].startswith("CLP")
    # Sin IA: Kubernetes no está en el perfil -> el motor de evidencias responde la verdad (0 años), no inventa.
    assert values["f6"] == "0" and questions == []
    saved.put("¿Cuántos años has trabajado con Kubernetes?", "0")
    values, questions = resolve(fields, profile, SavedAnswers(tmp_path / "answers.yaml"), {"cv": "x"}, {})
    assert values["f6"] == "0" and not questions


def test_cli_end_to_end(tmp_path):
    (tmp_path / "candidate").mkdir()
    shutil.copy(PACKAGE_ROOT / "candidate" / "profile.example.yaml", tmp_path / "candidate" / "profile.yaml")
    job_file = PACKAGE_ROOT / "examples" / "job_analista_datos.txt"
    root = ["--root", str(tmp_path)]
    assert main(root + ["run", "--file", str(job_file), "--id", "e2e", "--company", "X"]) == 0
    out = tmp_path / "data" / "outputs" / "e2e"
    for f in ("match.yaml", "cv_draft.yaml", "cv.docx", "cv.md", "audit.md", "interview.md"):
        assert (out / f).exists(), f

    # Un agente edita el borrador e inventa una cifra -> render debe bloquear.
    draft = load_yaml(out / "cv_draft.yaml")
    draft["summary"]["text"] += " Con 15 años liderando equipos."
    from cvtitan.utils import dump_yaml
    dump_yaml(draft, out / "cv_draft.yaml")
    assert main(root + ["render", "e2e"]) == 1
    assert main(root + ["track", "update", "e2e", "--status", "applied"]) == 0
    assert DB(tmp_path / "data" / "cvtitan.db").get("e2e")["status"] == "applied"


def test_study_plan_for_fullstack_job(tax, profile):
    from cvtitan.interview import study_plan
    text = ("Desarrollador Full Stack\nRequisitos\n- Node.js y Express.\n- Bases de datos NoSQL.\n"
            "- Programación orientada a objetos.\n- Pruebas unitarias.")
    job = job_intel.analyze(text, tax, job_id="fs")
    m = evidence.match(job, profile, tax)
    plan = study_plan(job, m)
    urls = [i["url"] for b in plan for i in b["items"]]
    assert len(urls) == len(set(urls))                                   # sin repetidos
    assert "https://www.techinterviewhandbook.org/behavioral-interview/" in urls
    assert any("system-design-primer#database" in u for u in urls)
    assert any("coding-interview-university#data-structures" in u for u in urls)
    assert any("how-to-secure-anything#authentication" in u for u in urls)


def test_search_list_roundtrip(tmp_path):
    from cvtitan.apply.batch import is_job_url
    from cvtitan.apply.search import read_selected, write_list
    rows = [{"postular": "", "score": 80, "cargo": "A", "url": "https://www.getonbrd.com/jobs/programming/a"},
            {"postular": "", "score": 50, "cargo": "B", "url": "https://www.getonbrd.com/jobs/programming/b"}]
    path = write_list(rows, tmp_path / "busqueda.csv")
    text = path.read_text(encoding="utf-8-sig").replace(";80;", ";80;", 1)
    lines = text.splitlines()
    lines[2] = "x" + lines[2]                       # el candidato marca solo la segunda
    path.write_text("\n".join(lines), encoding="utf-8-sig")
    assert read_selected(path) == ["https://www.getonbrd.com/jobs/programming/b"]
    assert not is_job_url("https://www.getonbrd.com/jobs/tag/python")
    assert is_job_url("https://www.getonbrd.com/jobs/programming/fullstack-developer-senior-bc-tecnologia-remote")


def test_motivation_answers_without_inventing(profile, tax):
    from cvtitan.apply.answers import rule_value
    job = {"title": "Analista BI", "company": None, "skills": [{"key": "python"}, {"key": "power_bi"}]}
    why = rule_value({"type": "textarea", "label": "¿Por qué te interesa trabajar en Acme?"}, profile, {}, job)
    assert "Acme" in why and "Python" in why and 50 <= len(why) <= 1000
    gross = rule_value({"type": "number", "label": "Expectativa de sueldo bruto (USD)"}, profile, {}, job)
    assert gross is None                            # el perfil de ejemplo no tiene bruto en USD: se pregunta


def test_keyword_dictionary_sources(tmp_path):
    from cvtitan.apply.search import search_sources
    cfg = tmp_path / "kw.yaml"
    cfg.write_text("groups:\n  mineria:\n    sources: [computrabajo, linkedin]\n    keywords: [despacho mina]\n"
                   "  software:\n    sources: [getonboard]\n    keywords: [python]\n", encoding="utf-8")
    urls = search_sources([], ["getonboard", "computrabajo"], "Chile", path=cfg)
    assert urls == ["https://cl.computrabajo.com/trabajo-de-despacho-mina", "https://www.getonbrd.com/jobs-python"]
    assert search_sources([], ["linkedin"], "Chile", ["mineria"], path=cfg)[0].startswith(
        "https://www.linkedin.com/jobs/search/?keywords=despacho+mina")
    assert search_sources(["sql"], ["getonboard"], "Chile", path=cfg) == ["https://www.getonbrd.com/jobs-sql"]


def test_cv_language_choice(tmp_path, tax):
    from cvtitan.engine import Engine
    from cvtitan.job_intel import detect_language
    from cvtitan.utils import Workspace, dump_yaml, load_yaml
    assert detect_language("We are hiring a data engineer. You will work with our team and the cloud.") == "en"
    assert detect_language("Buscamos un analista de datos con experiencia en SQL para el equipo.") == "es"
    (tmp_path / "candidate" / "documents").mkdir(parents=True)
    (tmp_path / "candidate" / "documents" / "cv_en.pdf").write_bytes(b"%PDF en")
    prof = load_yaml(PACKAGE_ROOT / "candidate" / "profile.example.yaml")
    prof["cv_files"] = {"en": "candidate/documents/cv_en.pdf"}
    dump_yaml(prof, tmp_path / "candidate" / "profile.yaml")
    eng = Engine(Workspace(tmp_path))
    _, profile = eng.load()
    en = eng.choose_cv({"job_id": "j1", "language": "en"}, profile, "adaptado.pdf")
    es = eng.choose_cv({"job_id": "j2", "language": "es"}, profile, "adaptado.pdf")
    de = eng.choose_cv({"job_id": "j3", "language": "de"}, profile, "adaptado.pdf")
    assert en["cv"].endswith("cv_en.pdf") and en["cv_kind"] == "original"
    assert es == {"cv": "adaptado.pdf", "cv_lang": "es", "cv_kind": "adaptado"}
    assert de["cv"].endswith("cv_en.pdf") and de["cv_lang"] == "en"      # sin alemán: inglés


def test_search_relevance_filter():
    from cvtitan.apply.search import is_relevant, keyword_of
    assert keyword_of("https://www.chiletrabajos.cl/trabajos/despacho-mina") == "despacho mina"
    assert keyword_of("https://cl.indeed.com/jobs?q=power+bi&l=Chile") == "power bi"
    assert keyword_of("https://careers.bhp.com/search/?q=&locationsearch=Chile") is None
    assert is_relevant("Despachador de flota para faena minera, turno 7x7", {"despacho mina"}) is False
    assert is_relevant("Operador de despacho en mina a rajo abierto", {"despacho mina"})
    assert is_relevant("Analista de datos para empresa minera", {"ingeniero de datos mineria", "analista de datos mineria"})
    assert not is_relevant("Auxiliar de aseo en cocina", {"mine controller"})
    assert is_relevant("Cualquier aviso", set())                 # portales de empresa: sin filtro


def test_market_analysis(profile):
    from cvtitan.market import analyze_market
    recs = [
        {"url": "a", "salary": {"salary_min": 3000, "salary_max": 4000, "salary_currency": "USD"},
         "skills": [{"key": "python", "name": "Python", "importance": "required", "weight": 3},
                    {"key": "azure", "name": "Azure", "importance": "required", "weight": 3}]},
        {"url": "b", "salary": {"salary_min": 1500000, "salary_max": None, "salary_currency": None},
         "skills": [{"key": "azure", "name": "Azure", "importance": "preferred", "weight": 1}]},
    ]
    res = analyze_market(recs, profile, {"USD": 1.0, "CLP": 0.001})
    demand = {d["key"]: d for d in res["demand"]}
    assert demand["azure"]["pct"] == 100.0 and not demand["azure"]["backed"]
    assert res["gaps"][0]["key"] == "azure" and res["gaps"][0]["avg_gain"] > 0
    assert res["median_usd"] == 2500                        # 3500 USD y 1.500.000 CLP -> 1500 USD
    assert [d["key"] for d in res["keywords"]] == ["python"]


RULES_FIXTURE = r"""
min_score: 55
salary_rule: minimo
exclude_temporary: false
allow_remote_part_time: true
include:
  datos: analista de datos|data engineer|reporting|\bbi\b
  software: desarroll|full.?stack
  ti: sistemas ti|\bti\b
  jefaturas: jefe de turno
exclude: operador|payroll|comercial|junior|\bjr\b
"""


def _fixture_rules(tmp_path):
    """Reglas de prueba propias: el motor se prueba sin depender de la configuración de cada usuario."""
    from cvtitan.autopilot import load_rules
    from cvtitan.utils import Workspace
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "auto.yaml").write_text(RULES_FIXTURE, encoding="utf-8")
    return load_rules(Workspace(tmp_path))


def test_autopilot_rules(tmp_path):
    from cvtitan.autopilot import decide
    rules = _fixture_rules(tmp_path)
    row = lambda cargo, score=80: {"cargo": cargo, "score": score, "vs_pretension": ""}  # noqa: E731
    assert decide(row("Analista de Datos Senior"), rules, {})[0]
    assert decide(row("Specialist Reporting"), rules, {})[0]
    assert decide(row("Desarrollador Full-Stack"), rules, {})[0]
    assert decide(row("Ingeniero/a de Mantención y Continuidad de Sistemas TI"), rules, {})[0]
    assert decide(row("Jefe de Turno Planta"), rules, {})[0]
    assert not decide(row("Operador de Planta"), rules, {})[0]
    assert not decide(row("Especialista HR Payroll Validation"), rules, {})[0]
    assert not decide(row("Ejecutivo Comercial"), rules, {})[0]
    assert not decide(row("Desarrollador Python", 40), rules, {})[0]          # bajo el ajuste mínimo


def test_autopilot_excludes_temporary_junior_and_low_salary(tmp_path):
    from cvtitan.autopilot import decide
    from cvtitan.job_intel import detect_contract
    rules = _fixture_rules(tmp_path)
    row = lambda cargo, **kw: {"cargo": cargo, "score": 80, "vs_pretension": "", **kw}  # noqa: E731
    # exclude_temporary: false -> se aceptan proyectos y trabajos a plazo.
    assert decide(row("Desarrollador Fullstack Python - Proyecto"), rules, {})[0]
    assert decide(row("Data Engineer", contrato="temporal (plazo fijo)"), rules, {})[0]
    assert not decide(row("Desarrollador Back-end Junior"), rules, {})[0]
    assert not decide(row("Analista de Datos", vs_pretension="bajo (-40%)"), rules, {})[0]
    assert decide(row("Analista de Datos", vs_pretension="ok"), rules, {})[0]
    assert detect_contract("DBA", "Modalidad híbrida por proyecto de 6 meses").startswith("temporal")
    assert detect_contract("DBA", "Contrato indefinido, beneficios") == ""


def test_autopilot_allows_remote_part_time_projects():
    from cvtitan.autopilot import decide, load_rules
    from cvtitan.job_intel import detect_workload
    from cvtitan.utils import Workspace
    rules = load_rules(Workspace(PACKAGE_ROOT))
    row = lambda cargo, **kw: {"cargo": cargo, "score": 80, "vs_pretension": "", **kw}  # noqa: E731
    side = row("Desarrollador Python", contrato="temporal (freelance)", jornada="parcial (20 horas semanales)",
               modalidad="remoto", vs_pretension="bajo (-60%)")
    assert decide(side, rules, {})[0]                                          # remoto + pocas horas: sí
    assert not decide({**side, "modalidad": "presencial"}, rules, {})[0]        # presencial: no
    assert not decide({**side, "jornada": ""}, rules, {})[0]                    # jornada completa: no
    assert detect_workload("Dev", "Trabajo remoto, 20 horas semanales, horario flexible").startswith("parcial")
    assert detect_workload("Dev", "Jornada completa de lunes a viernes") == ""


def test_salary_range_options_and_education():
    from cvtitan.apply.answers import _num, pick_range
    opts = ["Selecciona", "Hasta $2.000.000", "$2.000.001 - $3.500.000", "$3.500.001 - $4.000.000", "Más de $4.000.000"]
    assert pick_range(opts, 4_000_000) == "$3.500.001 - $4.000.000"
    assert pick_range(opts, 4_500_000) == "Más de $4.000.000"
    assert _num("CLP 4.000.000 mensuales") == 4_000_000 and _num("4 millones") == 4_000_000


def test_linkedin_profile_url_is_valid():
    from cvtitan.apply.answers import profile_url
    assert profile_url("linkedin.com/in/josé-pérez") == "https://www.linkedin.com/in/jos%C3%A9-p%C3%A9rez"
    assert profile_url("https://github.com/x") == "https://github.com/x"
    assert profile_url("") is None


# ---------------------------------------------------------------- Fase 2: guardián legal, sueldo, secretos
def _real_like_profile(tmp_path, tax):
    import yaml
    from cvtitan.profile import Profile
    (tmp_path / "declarations.yaml").write_text(yaml.safe_dump({
        "citizenship": ["Chile"], "legal_residence": ["Chile"], "work_authorization": ["Chile"],
        "security_clearance": False, "needs_sponsorship_outside_authorized": True}), encoding="utf-8")
    data = yaml.safe_load((PACKAGE_ROOT / "candidate" / "profile.example.yaml").read_text(encoding="utf-8"))
    data["preferences"]["salary_gross"] = {"USD": 4000, "CLP": 4000000}
    (tmp_path / "profile.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return Profile.load(tmp_path / "profile.yaml", tax)


def test_legal_guard_never_declares_false_facts(tmp_path, tax):
    from cvtitan.apply.answers import rule_value
    prof = _real_like_profile(tmp_path, tax)
    us = {"country": "Estados Unidos", "skills": []}
    cl = {"country": "Chile", "skills": []}
    cb = lambda label: {"type": "checkbox", "label": label, "required": True}  # noqa: E731
    sel = lambda label: {"type": "select", "label": label, "required": True, "options": ["Yes", "No"]}  # noqa: E731
    assert rule_value(cb("I certify that I am a U.S. citizen or permanent resident *"), prof, {}, us) is None
    assert rule_value(cb("Declaro no tener antecedentes penales *"), prof, {}, cl) is None
    assert rule_value(cb("I hold an active Secret security clearance *"), prof, {}, us) is None
    assert rule_value(cb("Certifico que tengo residencia legal en Chile."), prof, {}, cl) == "sí"
    assert rule_value(cb("Declaro que he leído el aviso de privacidad *"), prof, {}, cl) == "sí"
    assert rule_value(sel("Are you legally authorized to work in the United States?"), prof, {}, us) == "No"
    assert rule_value(sel("Will you now or in the future require visa sponsorship?"), prof, {}, us) == "Yes"
    assert rule_value(sel("Can you work in the US without sponsorship?"), prof, {}, us) == "No"


def test_salary_currency_and_period(tmp_path, tax):
    from cvtitan.apply.answers import rule_value
    prof = _real_like_profile(tmp_path, tax)
    us = {"country": "Estados Unidos", "skills": []}
    assert rule_value({"type": "text", "label": "Desired annual salary (USD)"}, prof, {}, us) == "USD 48,000 per year"
    assert rule_value({"type": "number", "label": "Expected annual compensation"}, prof, {}, us) == "48000"
    assert rule_value({"type": "text", "label": "Hourly rate expectation (USD)"}, prof, {}, us) == "USD 25.00 per hour"
    assert rule_value({"type": "text", "label": "Pretensión de renta"}, prof, {}, {"country": "Chile", "skills": []}) \
        == "CLP 4.000.000 mensuales"


def test_secrets_are_redacted_before_disk():
    from cvtitan.apply.forms import redact_fields, redact_html
    f = redact_fields([{"type": "password", "label": "Password", "value": "s3cret"},
                       {"type": "text", "label": "RUT", "value": "11.111.111-1"},
                       {"type": "text", "label": "Email", "value": "a@b.c"}])
    assert [x["value"] for x in f] == ["[oculto]", "[oculto]", "a@b.c"]
    html = redact_html('<input type="password" value="s3cret"><input type=hidden value="tok">')
    assert "s3cret" not in html and "tok" not in html


def test_remote_eligibility():
    from cvtitan.apply.legal import remote_eligibility as r
    assert r("Fully remote, hiring across LATAM.", "Estados Unidos", "remoto").startswith("ok")
    assert r("Remote (US only). Must be authorized to work in the United States.", "Estados Unidos", "remoto") \
        .startswith("excluido")
    assert r("We are unable to sponsor visas.", "Canadá", "remoto").startswith("excluido")
    assert r("Onsite in Austin, TX.", "Estados Unidos", "presencial").startswith("excluido")
    assert r("Remote role. Competitive pay.", None, "remoto") == "ambiguo"


# ---------------------------------------------------------------- Fase 3: Línea B
def test_line_b_helpers():
    from cvtitan.apply.intl_sources import _salary_from_text, region_eligibility
    from cvtitan.line_b import fingerprint, title_matches
    line = {"keywords": ["python", "software engineer", "data analyst"], "exclude_titles": "junior|sales|intern"}
    assert title_matches("Senior Python Developer", [], line)
    assert not title_matches("Junior Python Developer", [], line)
    assert not title_matches("Account Executive", ["sales"], line)
    assert fingerprint("Acme Inc.", "Software Engineer (Remote)") == fingerprint("ACME", "Software Engineer")
    assert region_eligibility(["Worldwide"]).startswith("ok")
    assert region_eligibility(["LATAM", "Europe"]).startswith("ok")
    assert region_eligibility(["USA", "Canada", "USA timezones"]).startswith("excluido")
    assert region_eligibility(None) is None
    s = _salary_from_text("$170k - $200k")
    assert s["salary_min"] == 170000 and s["salary_period"] == "año"


def test_line_b_scoring_and_salary_floor():
    from cvtitan.line_b import score_line
    line = {"scoring": {"compatibility": 40, "eligibility": 25, "salary": 20, "experience": 15},
            "salary": {"min_monthly": 3000, "target_monthly": 5000}}
    m = {"score": 80}
    high, _ = score_line(m, 8, "ok: worldwide", 6000, True, (None, 15), line)
    unknown, _ = score_line(m, 8, "ok: worldwide", None, True, (None, 15), line)   # sin sueldo: neutro
    low, _ = score_line(m, 8, "ok: worldwide", 1500, True, (None, 15), line)
    ambiguous, _ = score_line(m, 8, "ambiguo", 6000, True, (None, 15), line)
    assert high > unknown > low and high > ambiguous


def test_llm_disabled_by_default(monkeypatch):
    from cvtitan import llm
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("CVTITAN_LLM_ENABLED", "0")
    assert not llm.available()
    monkeypatch.setenv("CVTITAN_LLM_ENABLED", "1")
    assert llm.available()


def test_remote_eligibility_word_boundaries_and_sponsorship():
    from cvtitan.apply.legal import remote_eligibility as r
    assert r("We build tools for military logistics teams", None, "remoto") == "ambiguo"   # 'military' ≠ ITAR
    assert r("This role requires ITAR compliance", None, "remoto").startswith("excluido")
    assert r("Hiring remote engineers; Chile eligible.", None, "remoto").startswith("ok")


def test_form_reveals_ineligibility_and_heard_from(tmp_path, tax):
    from cvtitan.apply.answers import rule_value
    prof = _real_like_profile(tmp_path, tax)
    job = {"url": "https://job-boards.greenhouse.io/acme/jobs/1", "skills": []}
    f = {"type": "text", "label": "Are you currently residing in the US?*", "required": True}
    assert rule_value(f, prof, {}, job) == "No" and f.get("_ineligible")        # no se postula: exige residir en EE. UU.
    g = {"type": "select", "label": "How did you hear about us?", "options": ["LinkedIn", "Job Board", "Other"]}
    assert rule_value(g, prof, {}, job) == "Job Board"
    assert rule_value({"type": "checkbox", "label": "Data Privacy * Confirm", "required": True}, prof, {}, job) == "sí"
