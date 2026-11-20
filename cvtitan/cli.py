"""CLI de CV TITAN. Ejecuta `cvtitan --help` o `python -m cvtitan --help`."""
from __future__ import annotations

from .colors import mark, tally
from . import i18n
from .commands import register_all
from .commands._common import CliError  # noqa: F401  (reexportado)

import argparse
import os
import sys
from pathlib import Path

from . import cv_writer, evidence, importer, interview, job_intel, recruiter
from .db import DB, STATUSES
from .i18n import t
from .profile import Profile
from .taxonomy import Taxonomy
from .utils import Workspace, dump_yaml, load_yaml, write_text

MIN_SCORE_TO_GENERATE = 30.0




# ---------------------------------------------------------------------- helpers
def _ctx(args):
    ws = Workspace.resolve(args.root)
    tax = Taxonomy.load(ws.taxonomy_path)
    return ws, tax


def _profile(ws, tax) -> Profile:
    profile = Profile.load(ws.profile_path, tax)
    errors, _ = profile.validate()
    if errors:
        raise CliError("El perfil tiene errores; ejecuta `cvtitan validate`.\n- " + "\n- ".join(errors))
    return profile


def _load_job(ws, job_id) -> dict:
    path = ws.job_dir(job_id) / "job.yaml"
    if not path.exists():
        raise CliError(f"Job '{job_id}' not found. Use `cvtitan jobs` to list them.")
    return load_yaml(path)


def _load_match(ws, job_id) -> dict:
    path = ws.out_dir(job_id) / "match.yaml"
    if not path.exists():
        raise CliError(f"Matching for '{job_id}' is missing. Run `cvtitan match {job_id}`.")
    return load_yaml(path)


def _read_job_text(args) -> tuple[str, dict]:
    meta = {"title": args.title, "company": args.company, "url": args.url}
    if args.url:
        fetched = job_intel.fetch_url(args.url)
        meta["title"] = meta["title"] or fetched["title"]
        meta["company"] = meta["company"] or fetched["company"]
        text = fetched["text"]
    elif args.file:
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    elif args.text:
        text = args.text
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        raise CliError("Provide the job with --url, --file, --text or via stdin.")
    if len(text.strip()) < 80:
        raise CliError("The description is too short. If the URL requires login (e.g. LinkedIn), "
                       "copy the posting text into a file and use --file.")
    return text, meta


# ---------------------------------------------------------------------- comandos
def cmd_validate(args):
    ws, tax = _ctx(args)
    profile = Profile.load(ws.profile_path, tax)
    errors, warnings = profile.validate()
    for e in errors:
        print(f"{t('cli.label_error')}  {e}")
    for w in warnings:
        print(f"{t('cli.label_warning')}  {w}")
    backed = len(profile.backed_keys())
    print(f"\nBacked skills: {backed} / {len(profile.skill_map)} · "
          f"Total experience: {profile.years_experience()} years")
    print("Profile is valid." if not errors else "Profile has errors.")
    return 1 if errors else 0


def cmd_import_cv(args):
    ws, tax = _ctx(args)
    path = Path(args.path)
    text = importer.extract_text(path)
    draft = importer.draft_profile(text, tax, source=path.name)
    out = ws.root / "candidate" / "profile.draft.yaml"
    dump_yaml(draft, out)
    print(f"Borrador creado: {out}")
    exps = draft["experience"]
    print(f"Detected experiences: {len(exps)} · achievements to review: {sum(len(e['achievements']) for e in exps)}")
    print(f"Detected skills (unbacked): {len(draft['detected_skills'])}")
    print("Next step: validate with the candidate and move the data into candidate/profile.yaml.")


def cmd_analyze(args):
    ws, tax = _ctx(args)
    text, meta = _read_job_text(args)
    job = job_intel.analyze(text, tax, title=meta["title"], company=meta["company"], url=meta["url"], job_id=args.id)
    d = ws.job_dir(job["job_id"])
    write_text(d / "raw.txt", text)
    dump_yaml(job, d / "job.yaml")
    write_text(d / "job.md", job_intel.to_markdown(job))
    print(f"Vacante analizada: {job['job_id']}")
    print(f"  {len(job['skills'])} skills · seniority={job['seniority']} · years={job['years_required']}")
    print(f"  {d / 'job.md'}")
    return job


def cmd_match(args, job_id=None):
    ws, tax = _ctx(args)
    job_id = job_id or args.job_id
    profile = _profile(ws, tax)
    job = _load_job(ws, job_id)
    m = evidence.match(job, profile, tax)
    out = ws.out_dir(job_id)
    dump_yaml(m, out / "match.yaml")
    write_text(out / "match.md", evidence.to_markdown(job, m))
    print(f"Evidence score: {m['score']}/100 (potential {m['potential_score']}) · {m['recommendation']}")
    print(f"  {out / 'match.md'}")
    return m


def cmd_approve(args):
    ws, _ = _ctx(args)
    m = _load_match(ws, args.job_id)
    m["approved"] = True
    dump_yaml(m, ws.out_dir(args.job_id) / "match.yaml")
    print(f"Matching for {args.job_id} approved.")


def _render_and_audit(ws, tax, profile, job, m, draft, pdf: bool) -> int:
    out = ws.out_dir(job["job_id"])
    write_text(out / "cv.md", cv_writer.render_markdown(draft))
    docx = cv_writer.render_docx(draft, out / "cv.docx")
    print(f"CV: {docx}")
    if pdf:
        pdf_path = cv_writer.try_pdf(docx)
        print(f"PDF: {pdf_path}" if pdf_path else
              "PDF not generated: install `pip install docx2pdf` (requires Microsoft Word) or export from Word.")
    a = recruiter.audit(draft, job, m, profile, tax)
    dump_yaml(a, out / "audit.yaml")
    write_text(out / "audit.md", recruiter.to_markdown(job, a))
    s = a["scores"]
    print(f"Audit: {'APPROVED' if a['passed'] else 'BLOCKED'} · integrity {s['integrity']} · "
          f"keywords {s['keyword_coverage']} · clarity {s['clarity']}")
    print(f"  {out / 'audit.md'}")
    return 0 if a["passed"] else 1


def cmd_generate(args, job_id=None):
    ws, tax = _ctx(args)
    job_id = job_id or args.job_id
    profile = _profile(ws, tax)
    job, m = _load_job(ws, job_id), _load_match(ws, job_id)
    if not m.get("approved") and not args.force:
        raise CliError(f"Matching is not approved. Review match.md and run `cvtitan approve {job_id}` "
                       "(o usa --force).")
    draft = cv_writer.build_draft(job, m, profile, tax, max_bullets=args.max_bullets)
    dump_yaml(draft, ws.out_dir(job_id) / "cv_draft.yaml")
    return _render_and_audit(ws, tax, profile, job, m, draft, args.pdf)


def cmd_render(args):
    ws, tax = _ctx(args)
    profile = _profile(ws, tax)
    job, m = _load_job(ws, args.job_id), _load_match(ws, args.job_id)
    path = ws.out_dir(args.job_id) / "cv_draft.yaml"
    if not path.exists():
        raise CliError(f"No hay borrador. Ejecuta `cvtitan generate {args.job_id}`.")
    return _render_and_audit(ws, tax, profile, job, m, load_yaml(path), args.pdf)


def cmd_audit(args):
    ws, tax = _ctx(args)
    profile = _profile(ws, tax)
    job, m = _load_job(ws, args.job_id), _load_match(ws, args.job_id)
    draft = load_yaml(ws.out_dir(args.job_id) / "cv_draft.yaml")
    a = recruiter.audit(draft, job, m, profile, tax)
    write_text(ws.out_dir(args.job_id) / "audit.md", recruiter.to_markdown(job, a))
    print(recruiter.to_markdown(job, a))
    return 0 if a["passed"] else 1


def cmd_interview(args, job_id=None):
    ws, tax = _ctx(args)
    job_id = job_id or args.job_id
    profile = _profile(ws, tax)
    job, m = _load_job(ws, job_id), _load_match(ws, job_id)
    path = ws.out_dir(job_id) / "interview.md"
    write_text(path, interview.build(job, m, profile))
    print(f"Interview guide: {path}")


def cmd_run(args):
    job = cmd_analyze(args)
    m = cmd_match(args, job["job_id"])
    if m["score"] < MIN_SCORE_TO_GENERATE and not args.force:
        print(f"\nScore {m['score']} < {MIN_SCORE_TO_GENERATE}: no CV generated. Use --force to apply anyway.")
        return 0
    ws, _ = _ctx(args)
    m["approved"] = True
    dump_yaml(m, ws.out_dir(job["job_id"]) / "match.yaml")
    args.force = True
    rc = cmd_generate(args, job["job_id"])
    cmd_interview(args, job["job_id"])
    db = DB(ws.db_path)
    if not db.get(job["job_id"]):
        s = job.get("salary") or {}
        db.upsert(job["job_id"], url=job.get("url"), company=job.get("company"), title=job["title"],
                  country=job.get("country"), modality=job.get("modality"), score=m["score"],
                  required_coverage=m["required_coverage"], salary_text=job_intel.format_salary(s) or None,
                  status="awaiting_review", status_detail="CV generated from the CLI; apply manually.")
    return rc


def cmd_jobs(args):
    ws, _ = _ctx(args)
    if not ws.jobs_root.exists():
        print("No hay vacantes analizadas.")
        return
    for d in sorted(ws.jobs_root.iterdir()):
        if not (d / "job.yaml").exists():
            continue
        job = load_yaml(d / "job.yaml")
        mp = ws.out_dir(d.name) / "match.yaml"
        score = load_yaml(mp).get("score") if mp.exists() else "—"
        print(f"{d.name:55} score={score!s:>5}  {job.get('company') or ''}")


def cmd_track(args):
    ws, _ = _ctx(args)
    db = DB(ws.db_path)
    if args.action in ("add", "update"):
        if not args.job_id or not args.status:
            raise CliError("Uso: cvtitan track add|update <job_id> --status <estado> [--notes ...]")
        if not db.get(args.job_id):
            info = {}
            jp = ws.job_dir(args.job_id) / "job.yaml"
            if jp.exists():
                job = load_yaml(jp)
                info = {"company": job.get("company"), "title": job.get("title"), "url": job.get("url"),
                        "country": job.get("country"), "modality": job.get("modality")}
            mp = ws.out_dir(args.job_id) / "match.yaml"
            if mp.exists():
                info["score"] = load_yaml(mp).get("score")
            db.upsert(args.job_id, **info)
        row = db.set_status(args.job_id, args.status, args.notes)
        print(f"{row['job_id']}: {row['status_label']}")
    elif args.action == "list":
        for r in db.list():
            print(f"{r['job_id']:50} {r['status_label']:22} {str(r.get('country') or '-'):12} "
                  f"score={r.get('score') if r.get('score') is not None else '-'!s:>5} {(r.get('applied_at') or '')[:10]}")
    else:
        s = db.stats()
        print(f"Postulaciones: {s['total']} (enviadas {s['sent']})")
        print(f"Por estado: {s['by_status']}")
        print(f"By country: {s['by_country']} · by work mode: {s['by_modality']}")
        print(f"Progress rate (screening or beyond): {s['response_rate']}%")
        print(f"Average score of advancing ones: {s['avg_score_advanced']} · of the rest: {s['avg_score_not_advanced']}")


def cmd_web(args):
    import threading
    import webbrowser

    import uvicorn

    from .web.app import create_app

    ws = Workspace.resolve(args.root)
    if not ws.profile_path.exists():
        raise CliError("No profile found. Run `cvtitan init` and fill in candidate/profile.yaml.")
    app = create_app(ws, headless=args.headless)
    url = f"http://127.0.0.1:{args.port}"
    print(f"TITAN CV at {url}  (Ctrl+C to quit)")
    if not args.no_open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


class RobotLock:
    """Un solo proceso a la vez usa el navegador del robot (data/robot.lock con el PID y el comando)."""

    def __init__(self, ws: Workspace, what: str):
        self.path = ws.root / "data" / "robot.lock"
        self.what = what

    @staticmethod
    def _alive(pid: int) -> bool:
        if sys.platform == "win32":
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return code.value == 259                                          # STILL_ACTIVE
        try:
            import os
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def __enter__(self):
        import os
        if self.path.exists():
            try:
                pid, what = self.path.read_text(encoding="utf-8").split("|", 1)
                if int(pid) != os.getpid() and self._alive(int(pid)):
                    raise CliError(f"Another CV TITAN process is using the robot browser: «{what}» "
                                   f"(PID {pid}). Wait for it to finish or close it and try again.")
            except ValueError:
                pass
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(f"{os.getpid()}|{self.what}", encoding="utf-8")
        return self

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except OSError:
            pass
        return False


def _quiet_process() -> None:
    """Prioridad baja para este proceso y sus Chrome: no compite con lo que estés haciendo."""
    if sys.platform != "win32":
        try:
            os.nice(5)
        except (AttributeError, OSError):
            pass
        return
    if sys.platform == "win32":
        try:
            import ctypes
            BELOW_NORMAL = 0x4000
            k32 = ctypes.windll.kernel32
            k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL)
        except Exception:
            pass


def cmd_postular(args):
    with RobotLock(Workspace.resolve(args.root), "cvtitan postular"):
        return _cmd_postular(args)


def _cmd_postular(args):
    from .apply.batch import BatchApplier, linkedin_search_url

    ws = Workspace.resolve(args.root)
    if not ws.profile_path.exists():
        raise CliError("No profile found. Run `cvtitan init` and fill in candidate/profile.yaml.")
    _quiet_process()
    sources = list(args.urls)
    if args.pendientes:
        from .db import DB
        db = DB(ws.db_path)
        pending = [r["url"] for r in db.list() if r["status"] in ("needs_input", "awaiting_review") and r.get("url")]
        if not pending:
            raise CliError("No hay postulaciones pendientes.")
        print(f"{len(pending)} pending application(s).")
        sources += pending
    if args.lista:
        from .apply.search import read_selected
        lista = Path(args.lista)
        if not lista.exists():
            raise CliError(f"{lista} does not exist. Create it with `cvtitan buscar`.")
        selected = read_selected(lista)
        if not selected:
            raise CliError(f"No job marked in {lista} (put an x in the «postular» column).")
        print(f"{len(selected)} job(s) marked in {lista}."
              + ("" if args.confirmar else " Submitting without asking: you selected them."))
        sources += selected
    for kw in args.linkedin or []:
        sources.append(linkedin_search_url(kw, args.lugar, easy_apply=not args.todas))
    if not sources:
        raise CliError("Provide at least one URL (job or listing) or --linkedin \"keywords\".")
    headless = not args.ver
    applier = BatchApplier(ws, headless=headless, force=args.force or bool(args.lista) or args.pendientes,
                           auto_submit=bool(args.lista) and not args.confirmar,
                           unattended=bool(args.lista) and not args.ver,
                           login_window=not args.sin_ventanas)
    try:
        summary = applier.run(sources, limit=max(args.max, len(sources)) if (args.lista or args.pendientes)
                              else args.max, direct=bool(args.lista or args.pendientes) and not args.urls)
    except Exception as e:
        if "user data directory is already in use" in str(e).lower() or "ProcessSingleton" in str(e):
            raise CliError("The robot browser is already open (is `cvtitan web` running?). "
                           "Close it and try again.") from e
        raise
    print("\nResumen:")
    for title, score, result in summary:
        print("  " + mark(result, f"[{score or '-':>5}] {title[:70]}  ->  {result}"))
    print()
    print("  " + tally([r for _, _, r in summary]))
    return 0


def cmd_showcase(args):
    """Centro de mando con datos 100 % simulados (rotulados) para demostraciones. No navega ni postula."""
    import threading

    from rich.console import Console

    from . import telemetry
    from .report import render_mission
    from .ui import showcase
    from .ui.dashboard import CommandCenter
    telemetry.STATE.reset()
    stop = threading.Event()
    worker = threading.Thread(target=showcase.run, args=(args.segundos,), kwargs={"stop": stop}, daemon=True)
    with CommandCenter(mode="showcase", history_provider=lambda: {}):
        worker.start()
        try:
            while worker.is_alive():
                worker.join(0.2)
        except KeyboardInterrupt:
            stop.set()
            worker.join(2)
    Console(file=sys.stdout, highlight=False).print(render_mission(telemetry.snapshot(), {}))
    print("SHOWCASE: all figures above are SIMULATED for demonstration. Nothing was searched or submitted.")
    return 0


def cmd_demo(args):
    """Modo demostración: Chrome visible, en cámara lenta, resaltando y narrando cada paso. No envía nada
    salvo que se use --enviar (y aun así pregunta antes del clic final)."""
    with RobotLock(Workspace.resolve(args.root), "cvtitan demo"):
        from .apply import forms
        from .apply.batch import BatchApplier
        from .db import DB
        ws = Workspace.resolve(args.root)
        db = DB(ws.db_path)
        urls = list(args.urls)
        if not urls:                                    # sin URL: la próxima vacante en cola de reintentos
            queued = [r["url"] for r in db.list() if r.get("status") == "queued" and r.get("url")]
            if not queued:
                raise CliError("Provide a job URL, e.g. cvtitan demo https://www.getonbrd.com/jobs/...")
            urls = queued[:1]
        before = {u: (db.find_by_url(u) or {}).get("status") for u in urls}
        print("TITAN CV - DEMO MODE")
        print("  Chrome opens visibly in slow motion. Each field is outlined in blue before it is filled,")
        print("  and every step is narrated here: [OPEN] page, [CLICK] button, [FILL] field = value.")
        print("  " + ("Submission ENABLED: you will be asked before the final click." if args.enviar
                      else "Nothing will be submitted: the demo stops before the final click."))
        print()
        forms.DEMO = {"delay": args.lento, "say": print, "send": args.enviar}
        try:
            applier = BatchApplier(ws, headless=False, force=True, auto_submit=False, unattended=False,
                                   login_window=True)
            applier.runner.slow_mo = max(applier.runner.slow_mo, args.lento // 4)
            summary = applier.run(urls, limit=len(urls), direct=True)
        finally:
            forms.DEMO = None
        for u in urls:                                  # la demostración no cambia el estado de la vacante
            row = db.find_by_url(u)
            if row and row.get("status") == "awaiting_review" and str(row.get("status_detail", "")).startswith("Not submitted"):
                db.set_status(row["job_id"], before.get(u) or "queued", "Demo run: not submitted.")
        print("\nDemo summary:")
        for title, score, result in summary:
            print("  " + mark(result, f"[{score or '-':>5}] {title[:70]}  ->  {result}"))
        return 0


def cmd_buscar(args):
    with RobotLock(Workspace.resolve(args.root), "cvtitan buscar"):
        return _cmd_buscar(args)


def _cmd_buscar(args):
    from .apply.search import run_search

    ws = Workspace.resolve(args.root)
    where = [w.strip().lower().replace(" ", "") for w in args.en.split(",")]
    out = Path(args.salida) if args.salida else ws.root / "data" / "busqueda.csv"
    groups = [g.strip() for g in args.grupo.split(",")] if args.grupo else None
    try:
        _quiet_process()
        path, rows = run_search(ws, args.palabras, where, args.lugar, args.url or [], args.max, out, not args.ver,
                                groups, companies=not args.sin_empresas)
    except ValueError as e:
        raise CliError(str(e)) from e
    print(f"\n{len(rows)} job(s) in {path}")
    print("Open it in Excel, put an x in the «postular» column for the ones you want, save and run:")
    print(f"  cvtitan postular --lista {path}")
    return 0


def cmd_sesiones(args):
    with RobotLock(Workspace.resolve(args.root), "cvtitan sesiones"):
        return _cmd_sesiones(args)


def _cmd_sesiones(args):
    """Abre un Chrome NORMAL con el perfil del robot y las páginas de login, para iniciar sesión una vez.
    (Google bloquea el login en navegadores controlados por programas.) CV TITAN no ve tus contraseñas."""
    from .apply.human_browser import open_for_login, wait_closed
    from .apply.platforms import login_targets
    from .apply.search import COMPANIES_PATH, load_companies

    ws = Workspace.resolve(args.root)
    targets = [(t["name"], t["url"]) for t in login_targets()]
    cpath = ws.root / "config" / "companies.yaml"
    for c in load_companies(cpath if cpath.exists() else COMPANIES_PATH):
        if c.get("ats") in ("successfactors", "manual"):
            targets.append((c["name"], c.get("login_url") or c["url"]))
    if args.solo:
        wanted = [w.strip().lower() for w in args.solo.split(",")]
        targets = [t for t in targets if any(w in t[0].lower() for w in wanted)]
    if not targets:
        raise CliError("No portal matches --solo.")
    print("Chrome will open (regular, not automated) with one tab per portal:")
    for name, url in targets:
        print(f"  - {name}: {url}")
    print("\nSign in on each tab («Continue with Google» works too).")
    print("When done, CLOSE the Chrome window: sessions are saved for the robot.")
    try:
        proc = open_for_login(ws.browser_profile, [u for _, u in targets])
    except RuntimeError as e:
        raise CliError(str(e)) from e
    wait_closed(proc, profile_dir=ws.browser_profile)
    print("Done. Upcoming searches and applications will use these sessions.")
    return 0


def cmd_mercado(args):
    from . import market

    ws = Workspace.resolve(args.root)
    lista = Path(args.lista) if args.lista else ws.root / "data" / "busqueda.csv"
    if not lista.exists():
        raise CliError(f"No existe {lista}. Ejecuta `cvtitan buscar` primero.")
    out, res = market.run(ws, lista)
    print(f"\n{res['n']} jobs analyzed · {res['with_salary']} with published salary")
    print("\nMost requested:")
    for d in res["demand"][:10]:
        print(f"  {d['pct']:>5}%  {d['name']:<35} {'respaldada' if d['backed'] else 'BRECHA'}")
    print("\nGaps that would raise your average fit the most:")
    for d in res["gaps"][:6]:
        print(f"  +{d['avg_gain']:<5} pts  {d['name']} (in {d['jobs']} jobs)")
    print(f"\nInforme completo: {out}")
    return 0


MISSIONS = {"A": "LINE A · CHILE", "B": "LINE B · INTERNATIONAL", "TODAS": "LINES A + B"}
# Modo -> (línea, simulación forzada). None = usa --linea / --simular.
MODE_PLAN = {"hunter": ("A", True), "global": ("B", True), "analysis": ("TODAS", True),
             "apply": (None, None), "debug": (None, None), "stealth": (None, None)}


def _use_dashboard(args) -> bool:
    if args.log or args.modo == "stealth":
        return False
    try:
        from .ui.dashboard import available
    except ImportError:                      # Rich no instalado: salida de texto
        return False
    return available()


def _boot_checks(ws, args) -> list:
    """Comprobaciones REALES que muestra la secuencia de arranque."""
    from . import telemetry

    def profile():
        from .profile import Profile
        from .taxonomy import Taxonomy
        p = Profile.load(ws.profile_path, Taxonomy.load(ws.taxonomy_path))
        backed = sum(1 for sk in p.skill_map.values() if sk.get("status") == "backed")
        return True, f"{backed} backed skills · {p.years_experience()} yrs experience"

    def declarations():
        path = ws.root / "candidate" / "declarations.yaml"
        return (True, "legal declarations confirmed") if path.exists() else (None, "declarations.yaml missing")

    def database():
        from .db import DB
        return True, f"{len(DB(ws.db_path).list())} records in data/cvtitan.db"

    def registry():
        from .registry import Registry
        st = Registry(ws.db_path).stats()
        return True, f"{st['vacancies']} jobs · {st['employers']} employers"

    def lines():
        from .utils import load_yaml
        cfg = (load_yaml(ws.root / "config" / "lines.yaml") or {}).get("lines") or {}
        flags = " · ".join(f"{k}: send {'ON' if (v or {}).get('send_enabled') else 'OFF'}" for k, v in cfg.items())
        return True, flags or "no lines configured"

    def browser():
        from .apply.human_browser import find_chrome
        path = find_chrome()
        return (True, "Google Chrome found") if path else (None, "Chrome not found (Playwright Chromium fallback)")

    def network():
        import socket
        with socket.create_connection(("www.getonbrd.com", 443), timeout=3):
            pass
        return True, "job boards reachable (HTTPS)"

    def ai_engine():
        st, detail = telemetry.llm_status(ws.root)
        return (True if st == "ONLINE" else None), detail

    def linkedin():
        st, detail = telemetry.linkedin_status(ws.root, not args.sin_linkedin)
        return (True if st == "READY" else None), detail

    def monitor():
        import psutil  # noqa: F401
        return True, "psutil resource telemetry"

    return [("Candidate profile", profile), ("Legal guard", declarations), ("History database", database),
            ("Global registry (dedup)", registry), ("Mission lines", lines), ("Robot browser", browser),
            ("Network", network), ("AI engine (Claude)", ai_engine), ("LinkedIn guard", linkedin),
            ("System monitor", monitor)]


def purge_diagnostics(ws, days: int = 30) -> int:
    """Borra debug_page.html / debug_fields.json de más de `days` días (contienen el formulario con tus datos).
    Las capturas de confirmación se conservan como evidencia de envío."""
    import time as _time
    cutoff, n = _time.time() - days * 86400, 0
    for name in ("debug_page.html", "debug_fields.json"):
        for p in (ws.root / "data" / "outputs").glob(f"*/{name}"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    n += 1
            except OSError:
                pass
    return n


def cmd_auto(args):
    linea_forced, sim_forced = MODE_PLAN[args.modo]
    args.linea = (linea_forced or args.linea or "TODAS").upper()
    if sim_forced:
        args.simular = True
    dashboard = _use_dashboard(args)
    if not args.log and not dashboard:
        from .banner import show
        ws0 = Workspace.resolve(args.root)
        ui_cfg = ((load_yaml(ws0.settings_path) if ws0.settings_path.exists() else {}).get("ui") or {})
        show({"A": "Line A · Chile: mining & technology", "B": "Line B · International, remote from Chile",
              "TODAS": "Lines A + B · Chile & international remote"}.get(args.linea, ""),
             effect=ui_cfg.get("text_effect", "unstable"))
    if args.log:                          # tarea programada (pythonw, sin consola): todo va a un archivo
        log = Path(args.log)
        if not log.is_absolute():
            log = Workspace.resolve(args.root).root / log
        log.parent.mkdir(parents=True, exist_ok=True)
        from .privacy import RedactingStream
        sys.stdout = sys.stderr = RedactingStream(open(log, "a", encoding="utf-8", buffering=1))
        from datetime import datetime
        print(f"\n===== {datetime.now():%Y-%m-%d %H:%M} · cvtitan auto =====")
    with RobotLock(Workspace.resolve(args.root), "cvtitan auto"):
        _quiet_process()
        ws = Workspace.resolve(args.root)
        if not ws.profile_path.exists():
            raise CliError("No profile found. Run `cvtitan init` and fill in candidate/profile.yaml.")
        reuse = None
        if args.reusar:
            reuse = Path(args.reusar) if args.reusar != "ultima" else ws.root / "data" / "busqueda.csv"
            if not reuse.exists():
                raise CliError(f"{reuse} does not exist.")
        linea = args.linea
        purge_diagnostics(ws)
        from datetime import datetime as _dt
        from . import telemetry
        stamp = f"{_dt.now():%Y%m%d-%H%M%S}-{args.modo}"
        runs = ws.root / "data" / "auto" / "runs"
        telemetry.STATE.reset()
        telemetry.mission(MISSIONS.get(linea, linea) + (" · SIMULATION" if args.simular else ""), args.modo)
        close_log = telemetry.record_to(runs / f"{stamp}.log")
        try:
            return _run_auto(args, ws, reuse, linea, dashboard)
        finally:
            close_log()
            from .report import mission_report
            text = mission_report(telemetry.snapshot(), telemetry.history(ws.db_path, ws.root))
            from .privacy import redact
            text = redact(text)
            (runs / f"{stamp}-report.txt").write_text(text, encoding="utf-8")
            from .report import render_mission, save_snapshot
            from .funnel import write as write_funnel
            write_funnel(list(telemetry.STATE.funnel), runs / f"{stamp}-funnel.csv",
                         ws.root / "data" / "auto" / "refs.json")
            snap, hist = telemetry.snapshot(), telemetry.history(ws.db_path, ws.root)
            save_snapshot(snap, hist, runs / f"{stamp}-report.json")
            if args.log:
                print("\n" + text)
            else:                                     # mismo estilo que el centro de mando
                from rich.console import Console
                Console(file=sys.stdout, highlight=False).print(render_mission(snap, hist))
            print(f"Report saved: {runs / (stamp + '-report.txt')}")


class _Tee:
    """Escribe en la terminal y, línea a línea, en el registro de la ejecución."""

    def __init__(self, stream, log):
        self.stream, self.log, self._buf = stream, log, ""

    def write(self, s):
        self.stream.write(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.log(line)
        return len(s)

    def flush(self):
        self.stream.flush()

    def isatty(self):
        return getattr(self.stream, "isatty", lambda: False)()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def _run_auto(args, ws, reuse, linea, dashboard) -> int:
    from . import telemetry
    if not dashboard:                         # salida de texto: también queda en el registro de la ejecución
        saved = sys.stdout
        sys.stdout = _Tee(saved, telemetry.log)
        try:
            return _auto_lines(args, ws, reuse, linea)
        finally:
            sys.stdout.flush()
            sys.stdout = saved
    from .ui.dashboard import MODES, CommandCenter
    settings = load_yaml(ws.settings_path) if ws.settings_path.exists() else {}
    helmet_opts = ((settings.get("ui") or {}).get("helmet") or {})
    from .ui.system_monitor import SystemMonitor
    if not args.sin_intro:
        from rich.console import Console
        from .ui.matrix_animation import boot
        boot(Console(file=sys.__stdout__, highlight=False), _boot_checks(ws, args), MODES[args.modo][0],
             helmet_opts=helmet_opts)
    telemetry.system("AI ENGINE", *telemetry.llm_status(ws.root))
    telemetry.system("LINKEDIN", *telemetry.linkedin_status(ws.root, not args.sin_linkedin))
    hist = telemetry.history(ws.db_path, ws.root)
    telemetry.agent("TITAN-MEMORY", "READY", f"{hist.get('records', 0)} records · {hist.get('total', 0)} sent")
    telemetry.agent("TITAN-SHIELD", "READY", "legal guard + dedup registry armed")
    with CommandCenter(mode=args.modo, helmet_opts=helmet_opts,
                       history_provider=lambda: telemetry.history(ws.db_path, ws.root),
                       monitor=SystemMonitor(disk_path=ws.root)):
        try:
            return _auto_lines(args, ws, reuse, linea)
        except KeyboardInterrupt:
            telemetry.log("Mission interrupted by user (Ctrl+C).", "warn")
            return 130
        except Exception as e:
            telemetry.log(f"CRITICAL: {type(e).__name__}: {e}", "error")
            raise
        finally:
            telemetry.finish()


def _auto_lines(args, ws, reuse, linea) -> int:
    """Ejecuta la(s) línea(s); la salida va a la terminal o, con el tablero, al registro de eventos."""
    from . import autopilot

    if linea in ("B", "TODAS"):
        from . import line_b
        if linea == "TODAS":
            print("=== LINE A — Chile: mining & technology ===")
            try:
                res_a = autopilot.run(ws, simulate=args.simular, reuse=reuse)
                for title, score, result in res_a.get("summary") or []:
                    print("  " + mark(result, f"[{score or '-':>5}] {title[:65]}  ->  {result}"))
                print()
                print("  " + tally([r for _, _, r in res_a.get("summary") or []]))
            except Exception as e:                  # una línea con problemas no detiene la otra
                print(f"Line A failed: {type(e).__name__}: {e}")
            print("\n=== LINE B — International, remote from Chile ===")
        res = line_b.run(ws, simulate=args.simular, use_linkedin=not args.sin_linkedin)
        for title, score, result in res.get("summary") or []:
            print("  " + mark(result, f"[{score or '-':>5}] {title[:65]}  ->  {result}"))
        if res.get("summary"):
            print()
            print("  " + tally([r for _, _, r in res["summary"]]))
        print(f"\nRun decisions: {res['decisions']}")
        return 0
    res = autopilot.run(ws, simulate=args.simular, reuse=reuse)
    if res["summary"]:
        print("\nResults:")
        for title, score, result in res["summary"]:
            print("  " + mark(result, f"[{score or '-':>5}] {title[:65]}  ->  {result}"))
    print(f"\nRun decisions: {res['decisions']}")
    return 0


def cmd_informe(args):
    """Último informe de ejecución, o el historial de postulaciones (texto plano)."""
    from .report import history_report
    ws = Workspace.resolve(args.root)
    if args.historial:
        print(history_report(ws.db_path, args.dias))
        return 0
    if args.ref:                                      # decodificar un código: única vía para ver la URL real
        from .privacy import resolve_ref
        urls = resolve_ref(args.ref, ws.db_path)
        if not urls:
            raise CliError(f"No job found for {args.ref}.")
        for u in urls:
            sys.__stdout__.write(f"{args.ref.upper()}  ->  {u}\n")
        return 0
    snaps = sorted((ws.root / "data" / "auto" / "runs").glob("*-report.json"))
    if snaps and not args.lista:
        import json

        from rich.console import Console

        from .report import render_mission
        data = json.loads(snaps[-1].read_text(encoding="utf-8"))
        Console(file=sys.stdout, highlight=False).print(render_mission(data["snapshot"], data.get("history")))
        print(f"({snaps[-1].name})")
        return 0
    reports = sorted((ws.root / "data" / "auto" / "runs").glob("*-report.txt"))
    if not reports:
        raise CliError("No run reports yet. Run `cvtitan auto` first, or use `cvtitan informe --historial`.")
    pick = reports[-1] if not args.lista else None
    if args.lista:
        for r in reports[-30:]:
            print(r.name)
        return 0
    print(pick.read_text(encoding="utf-8"))
    print(f"\n({pick})")
    return 0


def cmd_publish(args):
    """Publica la versión open source saneada (ver cvtitan/publish.py). Sin --push solo audita."""
    from .publish import run
    ws = Workspace.resolve(args.root)
    # --confirm PALABRA: la aprobación escrita por el usuario en el mismo comando (sin pregunta interactiva).
    ask = (lambda _prompt: args.confirm) if args.confirm else input
    res = run(ws.root, push=args.push, reset_history=args.reset_history, ask=ask)
    for f in res.findings:
        print(f"  FINDING  {f}")
    for name, ok, detail in res.steps:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    return 0 if res.ok else 1


def cmd_registro(args):
    from .db import DB
    from .registry import Registry
    ws = Workspace.resolve(args.root)
    reg = Registry(ws.db_path, worker="cli")
    if args.accion == "importar":
        counts = reg.import_history(DB(ws.db_path))
        print("History imported into the global registry:", counts)
    elif args.accion == "recuperar":
        print(f"In-progress jobs recovered after restart: {reg.recover_stale()}")
    st = reg.stats()
    print(f"\nGlobal registry: {st['vacancies']} jobs · {st['employers']} employers · {st['sources']} URLs "
          f"({st['multi_source']} jobs seen on more than one board)")
    for k, v in sorted(st["by_status"].items(), key=lambda kv: -kv[1]):
        print(f"  {k:<20} {v}")
    return 0


def cmd_geo(args):
    from .geo import Geo
    from .pipeline import CircuitBreaker, TaskQueue
    ws = Workspace.resolve(args.root)
    geo = Geo(ws.db_path)
    if args.accion == "cargar":
        d = ws.root / "data" / "geo"
        if not (d / "cities15000.txt").exists():
            raise CliError("GeoNames files missing in data/geo (countryInfo.txt, admin1CodesASCII.txt, "
                           "cities15000.txt).")
        print("Loading GeoNames catalog…")
        geo.load(d)
    st = geo.stats()
    print(f"Catalog: {st['countries']} countries · {st['regions']} regions · {st['cities']} cities (>15,000 pop.)")
    print(f"Exploration logged: {st['explored']} searches in {st['explored_countries']} countries")
    print("Task queue:", TaskQueue(ws.db_path).counts())
    for h in CircuitBreaker(ws.db_path).report():
        state = "ABIERTO" if h["open_until"] and h["open_until"] > __import__("cvtitan.utils", fromlist=["x"]).now_iso() \
            else "ok"
        print(f"  fuente {h['source']:<16} {state:<8} fallos seguidos: {h['failures']}")
    return 0


# ---------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cvtitan", description="TITAN CV — evidence-based CVs and autonomous job applications.")
    p.add_argument("--root", help="Workspace folder (default: the project folder or CVTITAN_HOME).")
    p.add_argument("--lang", choices=i18n.available(), help="Message language (default: CVTITAN_LANG or es).")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("validate", help="Validate the candidate profile.").set_defaults(func=cmd_validate)

    s = sub.add_parser("import-cv", help="Extract a draft profile from a PDF/DOCX/TXT.")
    s.add_argument("path")
    s.set_defaults(func=cmd_import_cv)

    def job_source(sp):
        sp.add_argument("--url")
        sp.add_argument("--file")
        sp.add_argument("--text")
        sp.add_argument("--title")
        sp.add_argument("--company")
        sp.add_argument("--id", help="Manual job ID.")

    s = sub.add_parser("analyze", help="01 Job Intelligence: analyze a job posting.")
    job_source(s)
    s.set_defaults(func=cmd_analyze)

    for name, func, hlp in (("match", cmd_match, "02 Evidence: fit matrix."),
                            ("approve", cmd_approve, "Approve the matching to generate a CV."),
                            ("audit", cmd_audit, "04 Recruiter: audit the current CV."),
                            ("interview", cmd_interview, "Generate an interview guide.")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("job_id")
        s.set_defaults(func=func)

    s = sub.add_parser("generate", help="03 CV Optimization: generate draft, DOCX and audit.")
    s.add_argument("job_id")
    s.add_argument("--force", action="store_true")
    s.add_argument("--pdf", action="store_true")
    s.add_argument("--max-bullets", type=int, default=5)
    s.set_defaults(func=cmd_generate)

    s = sub.add_parser("render", help="Re-render and audit cv_draft.yaml after editing.")
    s.add_argument("job_id")
    s.add_argument("--pdf", action="store_true")
    s.set_defaults(func=cmd_render)

    s = sub.add_parser("run", help="Full pipeline: analyze, match, generate, audit and interview.")
    job_source(s)
    s.add_argument("--force", action="store_true")
    s.add_argument("--pdf", action="store_true")
    s.add_argument("--max-bullets", type=int, default=5)
    s.set_defaults(func=cmd_run)

    sub.add_parser("jobs", help="List analyzed jobs.").set_defaults(func=cmd_jobs)

    s = sub.add_parser("track", help="Application tracking.")
    s.add_argument("action", choices=["add", "update", "list", "stats"])
    s.add_argument("job_id", nargs="?")
    s.add_argument("--status", choices=STATUSES)
    s.add_argument("--notes")
    s.set_defaults(func=cmd_track)

    s = sub.add_parser("auto", help="Autopilot: search, filter with your rules and apply automatically.")
    s.add_argument("--linea", default=None, choices=["A", "B", "a", "b", "todas", "TODAS"],
                   help="A = Chile; B = international remote; todas = A then B (default).")
    s.add_argument("--sin-linkedin", action="store_true", help="Skip LinkedIn (public sources only).")
    s.add_argument("--simular", action="store_true", help="Show what would be applied to, without applying.")
    s.add_argument("--log", help="Write output to this file (for the scheduled task).")
    s.add_argument("--reusar", nargs="?", const="ultima",
                   help="Do not search again: reuse data/busqueda.csv (or the given CSV).")
    s.add_argument("--modo", default="apply", choices=["hunter", "global", "analysis", "apply", "stealth", "debug"],
                   help="hunter = discover in Chile (no submissions) · global = international scan (no submissions) · "
                        "analysis = score both lines (no submissions) · apply = authorized applications (default) · "
                        "stealth = minimal text UI · debug = command center with diagnostics.")
    s.add_argument("--sin-intro", action="store_true", help="Skip the boot animation.")
    s.set_defaults(func=cmd_auto)

    s = sub.add_parser("showcase", help="Command center filled with SIMULATED data for demonstrations "
                                         "(clearly labeled; nothing is searched or submitted).")
    s.add_argument("--segundos", type=float, default=60, help="Duration in seconds (default 60).")
    s.set_defaults(func=cmd_showcase)

    s = sub.add_parser("demo", help="Watch TITAN work: visible Chrome, slow motion, every field highlighted and "
                                     "narrated. Nothing is submitted unless --enviar.")
    s.add_argument("urls", nargs="*", help="Job URL(s). Without URL: the next job in the retry queue.")
    s.add_argument("--lento", type=int, default=700, help="Pause in ms before each action (default 700).")
    s.add_argument("--enviar", action="store_true", help="Allow the final submit (asks for confirmation first).")
    s.set_defaults(func=cmd_demo)

    s = sub.add_parser("publish", help="Audit (and optionally publish) the sanitized open-source release. Without "
                                        "--push it only audits; publishing requires typing PUBLICAR.")
    s.add_argument("--public", action="store_true", help="Target the public repository (default).")
    s.add_argument("--audit", action="store_true", help="Audit only (default behaviour without --push).")
    s.add_argument("--push", action="store_true", help="After all checks pass, commit and push (asks for approval).")
    s.add_argument("--confirm", metavar="PALABRA",
                   help="Approval typed in the command itself: PUBLICAR (with --push) or REESCRIBIR "
                        "(with --push --reset-history). Only used if every check passes.")
    s.add_argument("--reset-history", action="store_true",
                   help="With --push: replace the whole public history with one audited commit (asks REESCRIBIR).")
    s.set_defaults(func=cmd_publish)

    s = sub.add_parser("informe", help="Last run report (sites visited, applications) or the application history.")
    s.add_argument("--historial", action="store_true", help="Full application history from the database.")
    s.add_argument("--dias", type=int, help="With --historial: only the last N days.")
    s.add_argument("--lista", action="store_true", help="List saved run reports.")
    s.add_argument("--ref", help="Decode a job code (JOB-XXXXXXXX) into its real URL.")
    s.set_defaults(func=cmd_informe)

    s = sub.add_parser("geo", help="Geographic catalog (GeoNames), exploration, queue and source health.")
    s.add_argument("accion", nargs="?", default="estado", choices=["estado", "cargar"])
    s.set_defaults(func=cmd_geo)

    s = sub.add_parser("registro", help="Global de-duplication registry: status, import history, recover.")
    s.add_argument("accion", nargs="?", default="estado", choices=["estado", "importar", "recuperar"])
    s.set_defaults(func=cmd_registro)

    s = sub.add_parser("mercado", help="Market analysis of the last search: demand, gaps and salaries.")
    s.add_argument("--lista", help="Jobs CSV (default: data/busqueda.csv).")
    s.set_defaults(func=cmd_mercado)

    s = sub.add_parser("sesiones", help="Open the portals so you sign in once (sessions are saved).")
    s.add_argument("--solo", help="Only some portals, e.g. linkedin,bhp,codelco.")
    s.set_defaults(func=cmd_sesiones)

    s = sub.add_parser("buscar", help="Search jobs and create a CSV list for you to pick from.")
    s.add_argument("palabras", nargs="*",
                   help="Keywords. Without keywords, uses config/search_keywords.yaml.")
    s.add_argument("--grupo", help="Keyword groups, e.g. mineria,software (default: all).")
    s.add_argument("--en", default="getonboard,computrabajo,chiletrabajos,indeed,linkedin",
                   help="Sources: getonboard,computrabajo,chiletrabajos,indeed,linkedin (default: all).")
    s.add_argument("--sin-empresas", action="store_true",
                   help="Skip mining company career sites (config/companies.yaml).")
    s.add_argument("--lugar", default="Chile", help="LinkedIn location (default: Chile).")
    s.add_argument("--url", action="append", help="Extra listing URL (repeatable).")
    s.add_argument("--max", type=int, default=10, help="Max jobs per keyword and source (default: 10).")
    s.add_argument("--salida", help="Output CSV file (default: data/busqueda.csv).")
    s.add_argument("--ver", action="store_true", help="Show the Chrome window (default: hidden).")
    s.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_buscar)

    s = sub.add_parser("postular", help="Apply from the terminal to jobs or listings (with your confirmation).")
    s.add_argument("urls", nargs="*", help="Job or listing URLs (e.g. https://www.getonbrd.com/jobs-postgres).")
    s.add_argument("--linkedin", action="append", metavar="PALABRAS",
                   help="Search LinkedIn (Easy Apply). Repeatable: --linkedin python --linkedin \"power bi\".")
    s.add_argument("--lugar", default="Chile", help="LinkedIn search location (default: Chile).")
    s.add_argument("--todas", action="store_true", help="LinkedIn: include jobs without Easy Apply.")
    s.add_argument("--max", type=int, default=15, help="Max jobs per run (default: 15).")
    s.add_argument("--lista", help="CSV from `cvtitan buscar`: apply to rows marked with x without asking.")
    s.add_argument("--confirmar", action="store_true", help="With --lista: ask for confirmation before each submission.")
    s.add_argument("--force", action="store_true", help="Also process low-fit jobs.")
    s.add_argument("--sin-ventanas", action="store_true",
                   help="Never open windows: login or CAPTCHA steps stay pending.")
    s.add_argument("--pendientes", action="store_true",
                   help="Resume pending applications (login, CAPTCHA, questions). Use with --ver.")
    s.add_argument("--ver", action="store_true",
                   help="Show Chrome and ask you in the terminal. Default: hidden, no interruptions.")
    s.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_postular)

    s = sub.add_parser("web", help="Open the local web app: paste a link, apply and view history.")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--headless", action="store_true", help="Headless browser (not recommended).")
    s.add_argument("--no-open", action="store_true")
    s.set_defaults(func=cmd_web)

    register_all(sub)   # comandos ya migrados a cvtitan/commands/
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    i18n.set_language(args.lang)
    # Privacidad: nada de lo que se imprime muestra datos personales (nombre, correo, teléfono, ciudad, RUT...).
    from .privacy import RedactingStream, configure
    try:
        configure(Workspace.resolve(args.root).profile_path)
    except Exception:
        configure(None)
    try:
        from . import markets, scoring
        markets.configure(Workspace.resolve(args.root).root)
        scoring.configure(Workspace.resolve(args.root).root)
    except Exception:
        pass
    sys.stdout, sys.stderr = RedactingStream(sys.stdout), RedactingStream(sys.stderr)
    try:
        rc = args.func(args)
    except (CliError, FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return rc if isinstance(rc, int) else 0
