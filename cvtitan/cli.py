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

from .db import DB
from .profile import Profile
from .taxonomy import Taxonomy
from .utils import Workspace, load_yaml





# ---------------------------------------------------------------------- helpers
# ---------------------------------------------------------------------- comandos
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
        p = Profile.load(ws.profile_path, Taxonomy.load(ws.taxonomy_path))
        backed = sum(1 for sk in p.skill_map.values() if sk.get("status") == "backed")
        return True, f"{backed} backed skills · {p.years_experience()} yrs experience"

    def declarations():
        path = ws.root / "candidate" / "declarations.yaml"
        return (True, "legal declarations confirmed") if path.exists() else (None, "declarations.yaml missing")

    def database():
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cvtitan", description="TITAN CV — evidence-based CVs and autonomous job applications.")
    p.add_argument("--root", help="Workspace folder (default: the project folder or CVTITAN_HOME).")
    p.add_argument("--lang", choices=i18n.available(), help="Message language (default: CVTITAN_LANG or es).")
    sub = p.add_subparsers(dest="cmd", required=True)

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
