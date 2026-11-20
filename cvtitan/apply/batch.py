"""Postulación por lotes desde la terminal (sin la web).

    cvtitan postular <url de vacante o de listado> [...]
    cvtitan postular --linkedin "python developer" --lugar Chile --max 10

Para cada vacante: lee y analiza, filtra por compatibilidad, genera el CV adaptado, completa el formulario
y te pregunta en la terminal lo que no sabe. Antes de enviar muestra lo completado y pide confirmación
(«s» para enviar). Nunca envía sin tu «s», nunca resuelve CAPTCHA ni inicia sesión por ti.
"""
from __future__ import annotations

import re
from pathlib import Path
from datetime import date
from urllib.parse import quote_plus, urlparse

from ..db import PROCESS_STATUSES
from ..engine import Engine
from ..utils import Workspace, slugify
from .platforms import detect
from .runner import Runner

# Enlaces a una vacante concreta, por plataforma.
JOB_LINK_PATTERNS = [
    r"^https://(www\.)?getonbrd\.com/jobs/(?!tag/|city/|country/|seniority/|modality/|remote/)[^/]+/[^/?#]+$",
    r"^https://(www\.)?linkedin\.com/jobs/view/\d+",
    r"^https://[a-z]+\.computrabajo\.com/ofertas-de-trabajo/oferta-de-trabajo-",
    r"^https://(www\.)?laborum\.cl/empleos/[^?#]+\.html",
    r"^https://(www\.)?trabajando\.cl/trabajo/",
    r"^https://([a-z]+\.)?indeed\.com/(viewjob|rc/clk)",
    r"^https://(boards|job-boards)\.greenhouse\.io/[^/]+/jobs/\d+",
    r"^https://jobs\.lever\.co/[^/]+/[0-9a-f-]{36}$",
    r"^https://(www\.)?chiletrabajos\.cl/trabajo/[^/?#]+-\d+$",
    r"^https://(www\.)?bne\.(gob\.)?cl/ofertas/\d+$",
    # Portales SAP SuccessFactors (BHP, Teck, Codelco, CMP...): /job/<cargo>/<id>/
    r"^https://[^/]+/job/[^/?#]+/\d+(-[a-z]{2}_[A-Z]{2})?/?$",
]

# Enlaces + ids de tarjetas de LinkedIn (data-job-id / currentJobId), y desplaza las listas con scroll propio.
COLLECT_LINKS_JS = r"""() => {
  for (const el of document.querySelectorAll('.jobs-search-results-list, .scaffold-layout__list, [class*="jobs-search-results"]'))
    el.scrollTop = el.scrollHeight;
  const out = [...document.querySelectorAll('a[href]')].map(a => a.href);
  const host = location.hostname;
  if (/(^|\.)linkedin\.com$/.test(host)) {        // ids de tarjetas: SOLO dentro de LinkedIn
    for (const el of document.querySelectorAll('[data-job-id], [data-occludable-job-id]')) {
      const id = el.getAttribute('data-job-id') || el.getAttribute('data-occludable-job-id');
      if (/^\d+$/.test(id)) out.push('https://www.linkedin.com/jobs/view/' + id + '/');
    }
    for (const href of [...out]) {
      const m = href.match(/linkedin\.com\/jobs\/.*currentJobId=(\d+)/);
      if (m) out.push('https://www.linkedin.com/jobs/view/' + m[1] + '/');
    }
  }
  if (/(^|\.)indeed\.com$/.test(host))             // Indeed: solo dentro de Indeed
    for (const el of document.querySelectorAll('[data-jk]'))
      out.push(location.origin + '/viewjob?jk=' + el.getAttribute('data-jk'));
  return out;
}"""


def linkedin_search_url(keywords: str, location: str = "Chile", easy_apply: bool = True) -> str:
    url = f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(keywords)}&location={quote_plus(location)}"
    return url + ("&f_AL=true" if easy_apply else "")


def is_job_url(url: str) -> bool:
    return any(re.search(p, url) for p in JOB_LINK_PATTERNS)


def clean_job_url(url: str) -> str:
    url = url.split("#")[0]
    m = re.search(r"linkedin\.com/jobs/view/(\d+)", url)
    if m:
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}/"
    m = re.search(r"^(https://[a-z.]*indeed\.com)/(?:viewjob|rc/clk|pagead/clk)\?(?:.*&)?jk=([0-9a-f]+)", url)
    if m:
        return f"{m.group(1)}/viewjob?jk={m.group(2)}"
    if "indeed.com" in url:
        return url
    return url.split("?")[0]


class BatchApplier:
    def __init__(self, ws: Workspace, headless: bool = False, force: bool = False, ask=input, say=print,
                 auto_submit: bool = False, unattended: bool = False, login_window: bool = True,
                 login_timeout: int = 300):
        self.engine = Engine(ws)
        from .linkedin_guard import LinkedInGuard
        self.linkedin = LinkedInGuard(self.engine.settings, ws.root / "data" / "linkedin_guard.json")
        self.db = self.engine.db
        self.runner = Runner(self.engine, headless=headless)
        self.force = force
        self.auto_submit = auto_submit      # solo con vacantes que el candidato eligió en el listado
        self.unattended = unattended        # sin ventana ni preguntas: lo que requiera a la persona queda pendiente
        self.login_window = login_window    # login/CAPTCHA: abrir una ventana solo para eso y seguir solo
        self.login_timeout = login_timeout
        self.ask, self.say = ask, say
        self.summary: list[tuple[str, str, str]] = []
        self.failures: dict[tuple[str, str], int] = {}     # (portal, firma de la falla) -> veces en esta ejecución
        self.tripped: dict[str, str] = {}                   # portal -> motivo del corte
        import os
        from ..registry import Registry
        self.registry = Registry(ws.db_path, worker=f"pid{os.getpid()}")
        self.registry.recover_stale()
        self._vid: dict[str, int] = {}
        self.runner.on_before_submit = lambda jid: self._vid.get(jid) and self.registry.mark_clicked(self._vid[jid])

    # ------------------------------------------------------------------ vacantes
    def expand(self, url: str, limit: int) -> list[str]:
        """Una URL de vacante se devuelve tal cual; una de listado/búsqueda se recorre en el navegador."""
        if is_job_url(url):
            return [clean_job_url(url)]
        from .linkedin_guard import is_linkedin
        if is_linkedin(url):
            ok, why = self.linkedin.allow("search")
            if not ok:
                self.say(f"  LinkedIn: {why}; skipping the rest for now")
                return []
        page = self.runner.context().new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            self.runner.settle(page, 6000 if "linkedin.com" in url else 3500)
            links: list[str] = []
            for _ in range(6):                       # listados con carga perezosa (LinkedIn)
                for href in page.evaluate(COLLECT_LINKS_JS):
                    u = clean_job_url(href)
                    if is_job_url(u) and u not in links:
                        links.append(u)
                if len(links) >= limit:
                    break
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(1500)
            if not links and detect(url).requires_login:
                self.say(f"  No jobs found at {url}. Not signed in to {detect(url).name}?")
                return []
            return links[:limit] or [url]          # sin enlaces reconocibles: es una vacante de otro sitio
        finally:
            page.close()

    def job_id_for(self, url: str) -> str | None:
        prev = self.db.find_by_url(url)
        if prev and prev["status"] in PROCESS_STATUSES:
            return None
        if prev:
            return prev["job_id"]
        u = urlparse(url)
        host = (u.hostname or "").replace("www.", "").split(".")[0]
        tail = [p for p in u.path.split("/") if p][-1:] or [""]
        base = f"{date.today():%Y%m%d}-{slugify(host + '-' + tail[0], 50)}"
        job_id, n = base, 2
        while self.db.get(job_id):
            job_id, n = f"{base}-{n}", n + 1
        self.db.upsert(job_id, url=url, platform=detect(url).key, title=None, status="queued")
        return job_id

    # ------------------------------------------------------------------ interacción
    def _ask_questions(self, questions: list[dict]) -> dict:
        answers = {}
        self.say("  The form asks for things not in your profile (Enter = skip):")
        for q in questions:
            opts = q.get("options") or []
            hint = f" [{' / '.join(opts[:8])}]" if opts else (" [s/n]" if q["type"] == "checkbox" else "")
            value = self.ask(f"   · {q['label'][:160]}{hint}: ").strip()
            if q["type"] == "checkbox" and value:
                value = "sí" if value.lower() in ("s", "si", "sí", "y", "yes") else ""
            if value:
                answers[q["label"]] = value
        return answers

    def _review(self, job_id: str) -> bool:
        row = self.db.get(job_id)
        data = row.get("data") or {}
        from . import forms
        if forms.DEMO and not forms.DEMO.get("send"):
            self.say(f"\n  [DEMO] Form completed for: {row.get('title')} — {row.get('company')}")
            self.say("  [DEMO] Stopping BEFORE submit (nothing was sent). Use --enviar to submit with confirmation.")
            self.ask("  [DEMO] Review the form in Chrome, then press Enter to close... ")
            return False
        self.say(f"\n  READY TO SUBMIT: {row.get('title')} — {row.get('company')}")
        self.say(f"  Fit {row.get('score')} · {row.get('country') or '?'} · {row.get('modality') or '?'}")
        files = data.get("files") or {}
        if files.get("cv"):
            self.say(f"  CV attached: {files.get('cv_kind', 'tailored')} ({files.get('cv_lang', 'es')}) · "
                     f"{Path(files['cv']).name}")
        for f in (data.get("filled") or [])[-25:]:
            mark = "ok" if f.get("ok") else "--"
            self.say(f"   {mark} {f['label'][:70]}: {str(f['value'])[:90]}")
        if data.get("screenshot"):
            self.say(f"  Screenshot: {data['screenshot']}")
        if self.auto_submit:
            self.say("  Auto-submit: this job passed your rules.")
            return True
        self.say("  Check the Chrome window as well.")
        return self.ask("  Submit this application? [y/N]: ").strip().lower() in ("y", "yes", "s", "si", "sí")

    # ------------------------------------------------------------------ flujo
    # ------------------------------------------------------------------ ventana de login
    def _relaunch(self, headless: bool) -> None:
        """Cambia entre navegador oculto y visible (mismo perfil: las sesiones se conservan)."""
        if self.runner.headless == headless and self.runner.ctx is not None:
            return
        if self.runner.ctx is not None:
            try:
                self.runner.ctx.close()
            except Exception:
                pass
        self.runner.ctx = None
        self.runner.pages.clear()
        self.runner.headless = headless

    def _wait_for_login(self, job_id: str, url: str, kind: str) -> bool:
        """Cierra el navegador del robot, abre un Chrome NORMAL con el mismo perfil para que la persona
        inicie sesión (Google lo exige) y, cuando cierra esa ventana, el robot sigue oculto."""
        from .human_browser import open_for_login, wait_closed

        self._relaunch(headless=True)
        if self.runner.ctx is not None:
            try:
                self.runner.ctx.close()
            except Exception:
                pass
        self.runner.ctx = None
        self.runner.pages.clear()
        what = "solve the CAPTCHA" if kind == "captcha" else "sign in (tick «Remember me»)"
        self.say(f"  [LOGIN] Chrome opened: {what}, then CLOSE that window to continue "
                 f"({self.login_timeout // 60} min available).")
        try:
            proc = open_for_login(self.engine.ws.browser_profile, [url])
        except RuntimeError as e:
            self.say(f"  {e}")
            return False
        if not wait_closed(proc, self.login_timeout, profile_dir=self.engine.ws.browser_profile):
            return False
        self.say("  Window closed, continuing.")
        return True

    def _wait_for_login_in_robot(self, job_id: str, url: str, kind: str) -> bool:
        """Abre una ventana con la página que pide login/CAPTCHA y espera a que la persona termine.
        El robot no escribe contraseñas ni envía el formulario de acceso: solo detecta cuándo terminó."""
        from . import forms

        self._relaunch(headless=False)
        page = self.runner.page_for(job_id, url)
        try:
            page.bring_to_front()
        except Exception:
            pass
        what = "solve the CAPTCHA" if kind == "captcha" else "sign in (tick «Remember me»)"
        self.say(f"  [LOGIN] A window opened: {what}. I continue once you finish "
                 f"({self.login_timeout // 60} min; closing the window leaves it pending).")
        waited, clear = 0, 0
        while waited < self.login_timeout:
            try:
                if page.is_closed():
                    return False
                page.wait_for_timeout(3000)
                blocked = forms.has_captcha(page) if kind == "captcha" else forms.needs_login(page)
            except Exception:
                return False
            waited += 3
            clear = clear + 1 if not blocked else 0
            if clear >= 2:                   # dos revisiones seguidas sin login/CAPTCHA
                self.say("  Done, continuing.")
                return True
        return False

    def process(self, url: str) -> str:
        try:
            return self._process(url)
        finally:
            if self.runner.headless is False and self.unattended:
                self._relaunch(headless=True)     # vuelve a trabajar oculto para la siguiente vacante

    def _register(self, job_id: str, url: str) -> dict:
        row = self.db.get(job_id) or {}
        raw = self.engine.ws.job_dir(job_id) / "raw.txt"
        text = raw.read_text(encoding="utf-8")[:20000] if raw.exists() else None
        v = self.registry.register(url, row.get("company"), row.get("title"), row.get("country"), row.get("city"),
                                   row.get("modality"), source=row.get("platform"), text=text, job_id=job_id)
        self._vid[job_id] = v["id"]
        return v

    def _submit_once(self, job_id: str, url: str) -> str | None:
        """Envío idempotente: verifica, reclama (atómico), envía y registra el resultado. None = siguió el flujo."""
        v = self._register(job_id, url)
        ok, why = self.registry.can_submit(v["id"])
        if not ok:
            self.db.set_status(job_id, "skipped", f"Registro global: {why}")
            return f"skipped: {why}"
        if not self.registry.claim(v["id"]):
            return "skipped: another run is submitting this job"
        try:
            self.runner._submit(job_id)
        except Exception as e:
            self.registry.finish(v["id"], "failed", f"{type(e).__name__}: {e}")
            raise
        row = self.db.get(job_id)
        st, detail = row["status"], row.get("status_detail") or ""
        if st == "applied":
            self.registry.finish(v["id"], "confirmed", detail, (row.get("data") or {}).get("confirmation"))
        elif "Pulsé Enviar" in detail:
            self.registry.finish(v["id"], "unknown", detail)
        elif st == "needs_input":
            self.registry.finish(v["id"], "pending_review", detail)
        else:
            self.registry.finish(v["id"], "released", detail)     # volvió a completar el formulario: sin envío
        return None

    STRUCTURAL = ("unsure how to continue", "did not advance", "too many steps", "could not read the job",
                  "apply button not found", "error:")
    TRIP_AFTER = 3

    def _track_failure(self, portal: str, name: str, result: str) -> None:
        """Si un portal falla 3 veces por la MISMA causa estructural (p. ej. cambió su formulario), se corta el
        resto de sus vacantes en esta ejecución: no se pierde tiempo y se avisa para revisarlo."""
        import re
        low = result.lower()
        if not any(s in low for s in self.STRUCTURAL):
            return
        signature = re.sub(r"\d+|https?://\S+", "#", low)[:80]
        n = self.failures[(portal, signature)] = self.failures.get((portal, signature), 0) + 1
        if n >= self.TRIP_AFTER and portal not in self.tripped and portal != "generic":
            self.tripped[portal] = f"same failure {n}x: {signature[:50]}"
            from .. import telemetry
            msg = (f"ALERT {name}: the same failure happened {n} times in a row ({signature[:60]}). Skipping the rest "
                   f"of {name} in this run — the site probably changed its form; check debug_page.html.")
            self.say("  " + msg)
            telemetry.log(msg, "error")

    def _sent_today(self) -> int:
        """CV enviados hoy (todas las ejecuciones), según el historial."""
        from datetime import date
        today = date.today().isoformat()
        try:
            return sum(1 for r in self.db.list()
                       if r.get("status") == "applied" and str(r.get("applied_at") or "").startswith(today))
        except Exception:
            return 0

    def _process(self, url: str) -> str:
        self._registry_block = False
        result = self._process_inner(url)
        # Reflejar el desenlace en el registro global para no reintentar en vano en la próxima ejecución.
        # Si la vacante ni se procesó (el registro la bloqueó), su estado se deja tal cual.
        v = self.registry.by_url(url)
        if v and not self._registry_block and v["status"] not in ("SUBMITTED_CONFIRMED", "SUBMISSION_UNKNOWN",
                                                                  "IN_PROGRESS"):
            if result.startswith("skipped"):
                self.registry.set_status(v["id"], "CLOSED")
            elif result.startswith("pending"):
                self.registry.set_status(v["id"], "PENDING_REVIEW")
        return result

    def _process_inner(self, url: str) -> str:
        known = self.registry.by_url(url)
        if known:
            if known["status"] in ("SUBMITTED_CONFIRMED", "SUBMISSION_UNKNOWN"):
                when = str(known.get("submitted_at") or known.get("updated_at") or "")[:10]
                return f"done: already sent{(' on ' + when) if when else ''} (not re-sent)"
            ok, why = self.registry.can_submit(known["id"])
            if not ok:
                self._registry_block = True
                return f"skipped: {why}"
        job_id = self.job_id_for(url)
        if job_id is None:
            return "done: already sent (history, not re-sent)"
        self.runner._start(job_id, force=self.force)
        reviews = 0
        for _ in range(15):
            row = self.db.get(job_id)
            status, detail = row["status"], row.get("status_detail") or ""
            data = row.get("data") or {}
            if status == "needs_input":
                self.say(f"  [PEND] {detail}")
                kind = data.get("wait_kind")
                if kind == "captcha" and self.unattended:
                    return "pending: CAPTCHA (needs a human) -> `cvtitan postular --pendientes --ver`"
                if kind in ("login", "captcha") and self.login_window:
                    if not self._wait_for_login(job_id, row["url"], kind):
                        return "pending: login/CAPTCHA not completed -> `cvtitan postular --pendientes --ver`"
                    self.runner._resume(job_id)
                    continue
                if self.unattended or (self.runner.headless and kind != "questions"):
                    return f"pending: {detail} -> resolve with `cvtitan postular --pendientes --ver`"
                if data.get("wait_kind") == "questions" and data.get("questions"):
                    answers = self._ask_questions(data["questions"])
                    if not answers:
                        return "pending: unanswered questions"
                    self.runner._resume(job_id, answers=answers)
                else:
                    cmd = self.ask("  Do it in Chrome and press Enter to continue (or «s» to skip): ")
                    if cmd.strip().lower() in ("s", "o", "skip"):
                        return "skipped by you"
                    self.runner._resume(job_id)
            elif status == "awaiting_review":
                reviews += 1
                if reviews > 2:
                    shot = self.runner._shot(job_id, self.runner.pages.get(job_id), "sin_confirmacion") \
                        if self.runner.pages.get(job_id) else None
                    return ("pending: submitted but the platform showed no recognizable confirmation; "
                            f"check it on the portal{f' (screenshot: {shot})' if shot else ''}")
                if self.unattended and not self.auto_submit:
                    # review_mode: always: el robot dejó el formulario listo; el envío lo aprueba una persona.
                    self.db.set_status(job_id, "awaiting_review", "Awaiting your approval (review_mode: always).")
                    return "pending: awaiting your approval -> `cvtitan postular --pendientes --ver` or the web app"
                if not self._review(job_id):
                    self.db.set_status(job_id, "awaiting_review", "Not submitted: you left it pending in the terminal.")
                    return "not sent (your decision)"
                stop = self._submit_once(job_id, row["url"])
                if stop:
                    return stop
            elif status in ("applied", "skipped", "error", "cancelled"):
                return f"{status}: {detail}"
            else:
                return f"{status}: {detail}"
        return "stopped: too many steps"

    def run(self, sources: list[str], limit: int = 20, direct: bool = False) -> list[tuple[str, str, str]]:
        """direct=True: `sources` ya son URLs de vacantes concretas (Línea B, --lista): NO se tratan como listados."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            self.runner.pw = pw
            try:
                urls: list[str] = []
                for src in sources:
                    for u in ([src] if direct else self.expand(src, limit)):
                        if u not in urls:
                            urls.append(u)
                urls = urls[:limit]
                self.say(f"{len(urls)} job(s) to process.")
                from .. import telemetry
                telemetry.apply_begin(len(urls))
                telemetry.agent("TITAN-APPLY", "ACTIVE", "headless browser")
                for i, url in enumerate(urls, 1):
                    self.say(f"\n[{i}/{len(urls)}] {url}")
                    telemetry.apply_item(url)
                    portal = detect(url).key
                    try:
                        if portal in self.tripped:
                            result = f"skipped: {detect(url).name} circuit open ({self.tripped[portal]})"
                        else:
                            result = self.process(url)
                            self._track_failure(portal, detect(url).name, result)
                    except KeyboardInterrupt:
                        self.say("  Interrupted.")
                        break
                    except Exception as e:  # una página rara no detiene el lote
                        result = f"error: {type(e).__name__}: {e}"[:200]
                    row = self.db.find_by_url(url) or {}
                    title = " — ".join(filter(None, [row.get("title"), row.get("company")])) or url
                    self.summary.append((title, str(row.get("score") or ""), result))
                    from ..colors import mark, set_title, status_bar, kind
                    telemetry.apply_result(result, title=title, url=url)
                    self.say(f"  {mark(result)}")
                    results = [r for _, _, r in self.summary]
                    today = self._sent_today()
                    self.say("  " + status_bar(i, len(urls), results, today))
                    sent = sum(kind(r) == "ok" for r in results)
                    set_title(f"TITAN CV — {i}/{len(urls)} · {sent} CVs sent · today {today}")
            finally:
                if self.runner.ctx:
                    try:
                        self.runner.ctx.close()
                    except Exception:
                        pass
        return self.summary
