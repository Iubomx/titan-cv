"""Privacidad: ningún dato personal del candidato aparece en la terminal ni en los registros."""
import io

from cvtitan import privacy, telemetry
from cvtitan.utils import dump_yaml


def _setup(tmp_path):
    path = tmp_path / "profile.yaml"
    dump_yaml({"personal": {"name": "Ana María Pérez Soto", "first_name": "Ana María", "last_name": "Pérez Soto",
                            "email": "ana.perez@example.com", "phone": "+56 9 1234 5678",
                            "location": "Valparaíso, Chile", "linkedin": "linkedin.com/in/ana-perez"}}, path)
    privacy.configure(path)


def test_profile_values_and_generic_patterns_are_hidden(tmp_path):
    _setup(tmp_path)
    r = privacy.redact
    assert r("ok Nombre: Ana María") == "ok Nombre: [NAME]" and r("Apellidos: Pérez Soto") == "Apellidos: [NAME]"
    assert r("Email: ana.perez@example.com") == "Email: [EMAIL]"
    assert r("CV_ana_maria_perez_soto.pdf") == "CV_[NAME].pdf"
    upper = r("ANA MARIA PEREZ")
    assert "ANA" not in upper and "PEREZ" not in upper and "[NAME]" in upper
    assert r("Firma: Pérez") == "Firma: [NAME]"
    for phone in ("+56 9 1234 5678", "+56912345678", "912345678", "9 1234 5678"):
        assert r(f"Tel: {phone}") == "Tel: [PHONE]", phone
    assert "ana-perez" not in r("https://linkedin.com/in/ana-perez") and r("linkedin.com/in/ana-perez") == "[LINKEDIN]"
    assert r("Vive en Valparaíso, Chile") == "Vive en [CITY]"
    assert r("code sent to someone.else@example.org") == "code sent to [EMAIL]" and r("RUT 12.345.678-9") == "RUT [RUT]"
    # Lo que NO es dato personal queda intacto.
    for keep in ("Finished: 2026-11-18 10:43:06", "Offers discovered 1,665", "Not eligible from Chile", "20261118-104058-apply.log"):
        assert r(keep) == keep
    privacy.configure(None)


def test_stream_and_telemetry_never_carry_personal_data(tmp_path):
    _setup(tmp_path)
    out = io.StringIO()
    s = privacy.RedactingStream(out)
    s.write("[FILL] Correo = ana.perez@example.com\n[FILL] Teléfono = +56 9 1234 5678\nSubmit? [y/N]: ")
    s.flush()
    assert "ana.perez" not in out.getvalue() and "1234" not in out.getvalue() and out.getvalue().endswith("[y/N]: ")
    telemetry.STATE.reset()
    telemetry.log("[PEND] A verification code was sent to ana.perez@example.com")
    assert "ana.perez" not in str(telemetry.snapshot()["events"]) + str(telemetry.snapshot()["alerts"])
    privacy.configure(None)


def test_urls_are_masked_with_stable_reference_codes(tmp_path):
    import sqlite3
    url = "https://www.getonbrd.com/jobs/programming/frontend-engineer-cumplo-santiago"
    assert privacy.redact(f"[1/6] {url}") == f"[1/6] getonbrd.com #{privacy.ref(url)}"
    assert privacy.ref(url) == privacy.ref(url) and privacy.ref(url).startswith("JOB-") and len(privacy.ref(url)) == 12
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE applications (url TEXT)")
    con.execute("INSERT INTO applications VALUES (?)", (url,))
    con.commit()
    con.close()
    assert privacy.resolve_ref(privacy.ref(url).lower(), db) == [url]


def test_showcase_is_fully_labeled_as_simulated():
    from cvtitan.ui import showcase
    telemetry.STATE.reset()
    showcase.run(1.5, seed=3)
    s = telemetry.snapshot()
    assert "SIMULATED" in s["mission"]
    assert all(e[2].startswith("[SIM]") for e in s["events"] if e[2].strip())
    assert all(p["title"].startswith("[SIM]") for p in s["processed"])
    assert all("showcase.invalid" in p["url"] for p in s["processed"])   # nunca una URL real
