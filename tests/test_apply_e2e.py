"""Prueba de punta a punta del robot contra un portal de empleo falso servido en localhost."""
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cvtitan.utils import PACKAGE_ROOT, Workspace

JOB_PAGE = """<!doctype html><html><head><title>Analista de Datos - Minera Demo</title>
<script type="application/ld+json">{"@type":"JobPosting","title":"Analista de Datos","hiringOrganization":{"name":"Minera Demo"},
"jobLocation":{"address":{"addressLocality":"Antofagasta","addressCountry":"Chile"}},
"description":"<h3>Requisitos</h3><ul><li>Python y SQL avanzado (excluyente).</li><li>Power BI.</li><li>Experiencia en minería.</li><li>Automatización de reportes.</li></ul><h3>Deseable</h3><ul><li>Azure.</li></ul><p>Modalidad híbrida. Renta: $2.000.000 a $2.500.000 líquidos mensuales.</p>"}
</script></head><body><h1>Analista de Datos</h1><p>Minera Demo · Antofagasta</p>
<a href="/apply" role="button">Postular</a></body></html>"""

APPLY_PAGE = """<!doctype html><html><head><title>Postulación</title></head><body>
<form id="f" method="post" action="/submit" enctype="multipart/form-data">
 <div id="s1">
  <label for="fn">Nombre *</label><input id="fn" name="fn" required>
  <label for="ln">Apellidos *</label><input id="ln" name="ln" required>
  <label for="em">Correo electrónico *</label><input id="em" name="em" type="email" required>
  <label for="ph">Teléfono</label><input id="ph" name="ph">
  <label for="cv">Adjunta tu CV *</label><input id="cv" name="cv" type="file" required>
  <button type="button" onclick="next()">Siguiente</button>
 </div>
 <div id="s2" style="display:none">
  <label for="lic">¿Tienes licencia de conducir clase B? *</label>
  <select id="lic" name="lic"><option value="">Selecciona</option><option>Sí</option><option>No</option></select>
  <label for="sal">Pretensión de renta *</label><input id="sal" name="sal">
  <label><input type="checkbox" id="ok" name="ok"> Acepto la política de privacidad *</label>
  <button type="submit">Enviar postulación</button>
 </div>
</form>
<script>
function next(){ const ids=['fn','ln','em','cv']; if(ids.some(i=>!document.getElementById(i).value)) return;
  document.getElementById('s1').style.display='none'; document.getElementById('s2').style.display='block';
  for (const i of ['lic','sal','ok']) document.getElementById(i).required = true; }
</script></body></html>"""

received = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, code=200):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(JOB_PAGE if self.path.startswith("/job") else APPLY_PAGE)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        received["body"] = body
        self._send("<html><body><h1>¡Gracias por postular!</h1><p>Hemos recibido tu postulación.</p></body></html>")


def _chrome_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch(channel="chrome", headless=True).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _chrome_available(), reason="Google Chrome no disponible para Playwright")
def test_robot_fills_pauses_and_submits(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    (tmp_path / "candidate").mkdir()
    shutil.copy(PACKAGE_ROOT / "candidate" / "profile.example.yaml", tmp_path / "candidate" / "profile.yaml")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/job/123"

    from cvtitan.apply.runner import Runner
    from cvtitan.engine import Engine

    engine = Engine(Workspace(tmp_path))
    engine.settings["browser"] = {"channel": "chrome", "slow_mo_ms": 0}
    runner = Runner(engine, headless=True)
    runner.start()
    assert runner.ready.wait(30)
    db = engine.db

    def wait_for(*statuses, timeout=120):
        end = time.time() + timeout
        while time.time() < end:
            row = db.get("demo")
            if row and row["status"] in statuses:
                return row
            time.sleep(0.5)
        raise AssertionError(f"Estado final: {db.get('demo')['status']} · {db.events('demo')[-5:]}")

    try:
        db.upsert("demo", url=url, status="queued")
        runner.send("start", "demo")

        row = wait_for("needs_input", "awaiting_review", "error", "skipped")
        assert row["status"] == "needs_input", row["status_detail"]
        questions = row["data"]["questions"]
        assert [q["label"] for q in questions] == ["¿Tienes licencia de conducir clase B? *"], (
            row["status_detail"], row["data"].get("filled"), db.events("demo"))
        assert row["country"] == "Chile" and row["company"] == "Minera Demo"
        assert row["salary_min"] == 2000000 and row["modality"] == "híbrido"
        assert row["score"] > 30 and "Azure" not in row["skills_backed"]
        assert row["data"]["files"]["pdf"].endswith(".pdf")

        db.set_status("demo", "filling")
        runner.send("resume", "demo", answers={questions[0]["label"]: "Sí"}, remember=True)
        row = wait_for("awaiting_review", "needs_input", "error")
        assert row["status"] == "awaiting_review", row["status_detail"]
        assert "body" not in received                              # nada se envía sin confirmación
        assert (tmp_path / "data" / "outputs" / "demo" / "revision.png").exists()
        assert (tmp_path / "candidate" / "answers.yaml").exists()  # respuesta recordada

        db.set_status("demo", "submitting")
        runner.send("submit", "demo")
        row = wait_for("applied", "awaiting_review", "error", "needs_input")
        assert row["status"] == "applied", row["status_detail"]
        body = received["body"]
        for expected in (b"Camila", b"Rojas Fuentes", b"camila.rojas@example.com", b"CLP 2.000.000",
                         b".pdf", b"%PDF"):
            assert expected in body, expected
    finally:
        runner.send("stop")
        runner.join(20)
        server.shutdown()


@pytest.mark.skipif(not _chrome_available(), reason="Google Chrome no disponible para Playwright")
def test_cli_batch_asks_in_terminal_and_submits_only_on_yes(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    (tmp_path / "candidate").mkdir()
    shutil.copy(PACKAGE_ROOT / "candidate" / "profile.example.yaml", tmp_path / "candidate" / "profile.yaml")
    received.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/job/7"

    from cvtitan.apply.batch import BatchApplier

    prompts = []
    replies = iter(["Sí", "s"])                 # licencia de conducir, luego confirmar envío

    def ask(prompt):
        prompts.append(prompt)
        return next(replies)

    try:
        applier = BatchApplier(Workspace(tmp_path), headless=True, ask=ask, say=lambda *_: None)
        applier.engine.settings["browser"] = {"channel": "chrome", "slow_mo_ms": 0}
        summary = applier.run([url])
        assert summary[0][2].startswith("applied"), summary
        assert any("licencia" in p for p in prompts) and "Submit" in prompts[-1]
        assert b"Camila" in received["body"]

        # Segunda vez: el historial evita postular dos veces.
        again = BatchApplier(Workspace(tmp_path), headless=True, ask=ask, say=lambda *_: None)
        again.engine.settings["browser"] = {"channel": "chrome", "slow_mo_ms": 0}
        # El registro global bloquea el reenvío (antes lo hacía solo el historial por URL).
        assert again.run([url])[0][2].startswith("done: already sent")
    finally:
        server.shutdown()


@pytest.mark.skipif(not _chrome_available(), reason="Google Chrome no disponible para Playwright")
def test_linkedin_ids_only_collected_on_linkedin():
    from playwright.sync_api import sync_playwright
    from cvtitan.apply.batch import COLLECT_LINKS_JS
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True)
        page = b.new_page()
        page.set_content('<div data-job-id="1137572"></div><span data-jk="abc123"></span>'
                         '<a href="https://remoteok.com/remote-jobs/x-1137572">x</a>')
        links = page.evaluate(COLLECT_LINKS_JS)
        b.close()
    assert not any("linkedin.com" in u or "viewjob" in u for u in links)    # fuera de LinkedIn/Indeed: nada inventado


WIZARD_PAGE = """<!doctype html><html><body>
<h2>Cuéntanos sobre tu experiencia *</h2>
<div id="ed" contenteditable="true">Central Controller en Minera Demo desde 2022, gestionando flota con SQL y Python.</div>
<button id="next" type="submit" disabled>Siguiente</button>
<script>
document.getElementById('ed').addEventListener('keyup', () => {
  document.getElementById('next').disabled = document.getElementById('ed').innerText.trim().length < 20; });
</script></body></html>"""


def test_disabled_next_button_is_enabled_by_nudging_prefilled_editors():
    """Get on Board (2026): asistente con editores prellenados y «Siguiente» deshabilitado hasta teclear."""
    if not _chrome_available():
        pytest.skip("Chrome/Chromium no disponible")
    from playwright.sync_api import sync_playwright

    from cvtitan.apply import forms
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(WIZARD_PAGE)
        before = page.inner_text("#ed")
        assert forms.disabled_progress(page) and not forms.find_buttons(page)["next"]
        assert forms.nudge_inputs(page) == 1
        assert not forms.disabled_progress(page) and forms.find_buttons(page)["next"]
        assert page.inner_text("#ed") == before                       # el contenido no cambia
        browser.close()


@pytest.mark.skipif(not _chrome_available(), reason="Google Chrome no disponible para Playwright")
def test_demo_mode_narrates_highlights_and_never_submits(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / "candidate").mkdir()
    shutil.copy(PACKAGE_ROOT / "candidate" / "profile.example.yaml", tmp_path / "candidate" / "profile.yaml")
    received.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/job/demo"

    from cvtitan.apply import forms
    from cvtitan.apply.batch import BatchApplier

    lines, replies = [], iter(["Sí", ""])                 # licencia de conducir; luego Enter para cerrar la demo
    forms.DEMO = {"delay": 10, "say": lines.append, "send": False}
    try:
        applier = BatchApplier(Workspace(tmp_path), headless=True, ask=lambda p: next(replies), say=lines.append)
        applier.engine.settings["browser"] = {"channel": "chrome", "slow_mo_ms": 0}
        summary = applier.run([url])
    finally:
        forms.DEMO = None
        server.shutdown()
    text = "\n".join(map(str, lines))
    assert "[OPEN]" in text and "[CLICK]" in text and "[FILL] Nombre" in text
    assert "Stopping BEFORE submit" in text and summary[0][2].startswith("not sent")
    assert "body" not in received                           # nunca se envió el formulario
