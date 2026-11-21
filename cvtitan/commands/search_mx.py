"""Búsqueda de vacantes con ubicación estricta para México."""
from pathlib import Path

from ._common import _ctx, _profile
from ._robot import RobotLock


def register(sub) -> None:
    cmd = sub.add_parser("buscar-mx", help="Busca vacantes remotas desde México y con sede en Monterrey.")
    cmd.add_argument("--area", action="append", default=[],
                     help="Área repetible: proyectos, casinos, telecom, martech. Por defecto busca en todas.")
    cmd.add_argument("--dias", type=int, default=30, help="Ventana de publicaciones recientes (30 días).")
    cmd.add_argument("--meta", type=int, default=20, help="Meta de vacantes distintas por área (20).")
    cmd.add_argument("--salida", type=Path, help="Ruta del CSV (por defecto data/busqueda-mx.csv).")
    cmd.set_defaults(func=run)


def run(args) -> int:
    from ..search_mx import search

    if not 1 <= args.dias <= 365 or args.meta < 1:
        raise ValueError("--dias debe estar entre 1 y 365 y --meta debe ser positivo.")
    ws, taxonomy = _ctx(args)
    profile = _profile(ws, taxonomy)
    out = args.salida or ws.root / "data" / "busqueda-mx.csv"
    with RobotLock(ws, "cvtitan buscar-mx"):
        counts, found, undated = search(ws, profile, args.area, out, args.dias)
    print(f"{found} vacante(s) distintas en los últimos {args.dias} días · {out}")
    for area, count in counts.items():
        shortfall = f" · faltan {args.meta - count}" if count < args.meta else ""
        print(f"  {area}: {count}/{args.meta}{shortfall}")
    if undated:
        print(f"{undated} vacante(s) compatibles sin fecha comprobable quedaron fuera del CSV.")
    return 0
