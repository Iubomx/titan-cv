"""Auditoría del embudo 2026-11-18: niveles, motivos, falsos negativos y consistencia de métricas."""
import csv

from cvtitan import telemetry
from cvtitan.funnel import reason_category, summarize, tier_line_a, tier_line_b, write


def test_reason_categories_cover_both_lines():
    assert reason_category("daily cap reached (15)") == "daily cap"
    assert reason_category("Computrabajo bloquea la automatización: postula a mano") == "portal blocks automation"
    assert reason_category("ajuste 54.8 < 55") == "score below threshold"
    assert reason_category("cargo excluido (junior)") == "excluded title (junior, sales...)"
    assert reason_category("no se puede trabajar desde Chile: solo residentes") == "not eligible from Chile"
    assert reason_category("We Work Remotely exige cuenta del portal y no hallé") == "board account required"
    assert reason_category("registry: awaiting human review") == "registry: pending/sent"


def test_tiers_never_inflate_matches():
    assert tier_line_a("postular", "ajuste 70", 70, 55, 10) == "high"
    assert tier_line_a("descartada", "daily cap reached (15)", 64, 55, 10) == "held"
    assert tier_line_a("descartada", "Computrabajo bloquea la automatización", 90, 55, 10, manual_ok=True) == "manual"
    assert tier_line_a("descartada", "Computrabajo bloquea la automatización", 90, 55, 10, manual_ok=False) == "no"
    assert tier_line_a("descartada", "ajuste 47.0 < 55", 47, 55, 10) == "potential"
    assert tier_line_a("descartada", "ajuste 40.0 < 55", 40, 55, 10) == "no"           # fuera del margen
    assert tier_line_a("descartada", "cargo excluido (junior)", 90, 55, 10) == "no"   # otra regla falla: no es potencial
    assert tier_line_b("en espera", "Remote OK exige cuenta del portal", 60, 50, 10) == "review"
    assert tier_line_b("descartada", "puntaje 44.0 < 50", 44, 50, 10) == "potential"


def test_counters_are_consistent_and_exclusive():
    telemetry.STATE.reset()
    recs = [{"tier": t, "reason_category": rc} for t, rc in
            [("high", ""), ("held", "daily cap"), ("manual", "portal blocks automation"), ("potential", "score"),
             ("review", "board account required"), ("no", "off-target role"), ("no", "off-target role")]]
    telemetry.funnel(recs)
    c = telemetry.snapshot()["counters"]
    assert c["compatible"] == 3 and c["held_quota"] == 1 and c["manual_apply"] == 1
    assert c["potential"] == 1 and c["on_hold"] == 1 and c["discarded"] == 2
    assert c.get("pending", 0) == 0                     # «pending» = solo lo que espera al candidato tras procesar
    assert summarize(recs)["reasons"] == {"off-target role": 2}


def test_title_filter_false_negatives_fixed():
    from cvtitan import line_b
    line = {"keywords": ["software engineer", "backend", "full stack", "data engineer", "it support",
                         "integration specialist"],
            "exclude_titles": r"\bintern\b|internship|account executive"}      # línea de prueba propia
    for title in ("Senior Software Engineer, Backend (International Payments)", "Full-Stack Engineer",
                  "Senior Data Engineers", "IT Support Specialist", "Integration Specialist"):
        assert line_b.title_matches(title, [], line), title
    for title in ("Software Engineer Intern", "Firmware Engineer", "Account Executive"):
        assert not line_b.title_matches(title, [], line), title


def test_funnel_file_has_no_urls_and_refs_resolve(tmp_path):
    url = "https://www.getonbrd.com/jobs/programming/frontend-engineer-x"
    write([{"line": "A", "stage": "scored", "tier": "high", "title": "Frontend", "url": url}],
          tmp_path / "f.csv", tmp_path / "refs.json")
    text = (tmp_path / "f.csv").read_text(encoding="utf-8-sig")
    assert url not in text and "#JOB-" in text
    rows = list(csv.DictReader(text.splitlines(), delimiter=";"))
    assert rows[0]["tier"] == "high"
    import json
    assert url in json.loads((tmp_path / "refs.json").read_text(encoding="utf-8")).values()
