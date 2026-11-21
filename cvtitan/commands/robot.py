"""Comandos del robot de navegador: web, postular, showcase, demo, buscar y sesiones (movidos desde `cli.py`;
comportamiento sin cambios)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..colors import mark, tally
from ..utils import Workspace
from ._common import CliError
from ._robot import RobotLock, _quiet_process


def cmd_web(args):
    import threading
    import webbrowser

    import uvicorn

    from ..web.app import create_app

    ws = Workspace.resolve(args.root)
    if not ws.profile_path.exists():
        raise CliError("No profile found. Run `cvtitan init` and fill in candidate/profile.yaml.")
    app = create_app(ws, headless=args.headless)
    url = f"http://127.0.0.1:{args.port}"
    print(f"TITAN CV at {url}  (Ctrl+C to quit)")
    if not args.no_open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


def cmd_postular(args):
    with RobotLock(Workspace.resolve(args.root), "cvtitan postular"):
        return _cmd_postular(args)


def _cmd_postular(args):
    from ..apply.batch import BatchApplier, linkedin_search_url

    ws = Workspace.resolve(args.root)
    if not ws.profile_path.exists():
        raise CliError("No profile found. Run `cvtitan init` and fill in candidate/profile.yaml.")
    _quiet_process()
    sources = list(args.urls)
    if args.pendientes:
        from ..db import DB
        db = DB(ws.db_path)
        pending = [r["url"] for r in db.list() if r["status"] in ("needs_input", "awaiting_review") and r.get("url")]
        if not pending:
            raise CliError("No hay postulaciones pendientes.")
        print(f"{len(pending)} pending application(s).")
        sources += pending
    if args.lista:
        from ..apply.search import read_selected
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

    from .. import telemetry
    from ..report import render_mission
    from ..ui import showcase
    from ..ui.dashboard import CommandCenter
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
        from ..apply import forms
        from ..apply.batch import BatchApplier
        from ..db import DB
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
    from ..apply.search import run_search

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
    from ..apply.human_browser import open_for_login, wait_closed
    from ..apply.platforms import login_targets
    from ..apply.search import COMPANIES_PATH, load_companies

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


def register(sub) -> None:
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
