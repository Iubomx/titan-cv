"""CLI de CV TITAN. Ejecuta `cvtitan --help` o `python -m cvtitan --help`."""
from __future__ import annotations

from .colors import mark, tally
from . import i18n
from .commands import register_all
from .commands._common import CliError  # noqa: F401  (reexportado)
from .commands._robot import RobotLock, _quiet_process

import argparse
import sys
from pathlib import Path

from .db import DB
from .profile import Profile
from .taxonomy import Taxonomy
from .utils import Workspace, load_yaml





# ---------------------------------------------------------------------- helpers
# ---------------------------------------------------------------------- comandos
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
