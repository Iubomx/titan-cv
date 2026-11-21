"""Búsqueda de vacantes con ubicación estricta para México."""
from pathlib import Path

from ._common import _ctx, _profile
from ._robot import RobotLock


def register(sub) -> None:
    cmd = sub.add_parser("buscar-mx", help="Busca vacantes remotas desde México y con sede en Monterrey.")
    cmd.add_argument("--area", action="append", default=[],
                     help="Área repetible: proyectos, casinos, telecom, martech. Por defecto busca en todas.")
    cmd.add_argument("--salida", type=Path, help="Ruta del CSV (por defecto data/busqueda-mx.csv).")
    cmd.set_defaults(func=run)


def run(args) -> int:
    from ..search_mx import search

    ws, taxonomy = _ctx(args)
    profile = _profile(ws, taxonomy)
    out = args.salida or ws.root / "data" / "busqueda-mx.csv"
    with RobotLock(ws, "cvtitan buscar-mx"):
        found, total = search(ws, profile, args.area, out)
    print(f"{found} vacante(s) de {total} consultadas · {out}")
    return 0
