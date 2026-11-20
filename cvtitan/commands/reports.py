"""Informes y utilidades de datos: publish, informe, geo, registro y mercado (movidos desde `cli.py`;
comportamiento sin cambios)."""
from __future__ import annotations

import sys
from pathlib import Path

from ..db import DB
from ..utils import Workspace
from ._common import CliError


def cmd_mercado(args):
    from .. import market

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


def cmd_informe(args):
    """Último informe de ejecución, o el historial de postulaciones (texto plano)."""
    from ..report import history_report
    ws = Workspace.resolve(args.root)
    if args.historial:
        print(history_report(ws.db_path, args.dias))
        return 0
    if args.ref:                                      # decodificar un código: única vía para ver la URL real
        from ..privacy import resolve_ref
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

        from ..report import render_mission
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
    from ..publish import run
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
    from ..registry import Registry
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
    from ..geo import Geo
    from ..pipeline import CircuitBreaker, TaskQueue
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


def register(sub) -> None:
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
