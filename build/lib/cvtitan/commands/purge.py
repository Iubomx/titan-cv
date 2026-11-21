"""`cvtitan purge`: borra datos generados en data/ por grupos. Nunca toca candidate/ ni .env."""
from __future__ import annotations

import sys

from .. import purge as data_purge
from ..utils import Workspace
from ._common import CliError


def register(sub) -> None:
    s = sub.add_parser("purge", help="Delete data TITAN generated in data/ (never touches candidate/ or .env).")
    s.add_argument("--outputs", action="store_true", help="Generated CVs, analyses and screenshots.")
    s.add_argument("--sesiones", action="store_true", help="Browser sessions and LinkedIn guard state.")
    s.add_argument("--historial", action="store_true", help="History database, registry and mission reports.")
    s.add_argument("--cache", action="store_true", help="Search, market and geo caches.")
    s.add_argument("--todo", action="store_true", help="All of the above.")
    s.add_argument("--si", action="store_true", help="Do not ask for confirmation.")
    s.set_defaults(func=run)


def run(args) -> int:
    groups = list(data_purge.GROUPS) if args.todo else [
        g for g, on in (("outputs", args.outputs), ("sessions", args.sesiones),
                        ("history", args.historial), ("cache", args.cache)) if on]
    if not groups:
        raise CliError("Choose what to delete: --outputs, --sesiones, --historial, --cache or --todo.")
    ws = Workspace.resolve(args.root)
    paths = data_purge.plan(ws, groups)
    if not paths:
        print("Nothing to delete.")
        return 0
    print("Will delete:")
    for path in paths:
        print(f"  - data/{path.relative_to((ws.root / 'data').resolve()).as_posix()}")
    print("Never touched: candidate/ (profile, declarations, CVs) and .env.")
    if not args.si and input("Type 'borrar' to confirm: ").strip().lower() != "borrar":
        print("Cancelled. Nothing was deleted.")
        return 1
    done, failed = data_purge.execute(paths)
    print(f"Deleted {done} item(s).")
    if failed:
        print(f"Could not delete {len(failed)} item(s) (in use?). Close Chrome/TITAN and retry.", file=sys.stderr)
        return 1
    return 0
