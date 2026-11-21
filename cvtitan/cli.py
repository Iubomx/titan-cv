"""CLI de CV TITAN. Ejecuta `cvtitan --help` o `python -m cvtitan --help`."""
from __future__ import annotations

from . import i18n
from .commands import register_all
from .commands._common import CliError  # noqa: F401  (reexportado)
from .commands.auto import purge_diagnostics  # noqa: F401  (reexportado: lo usan las pruebas)

import argparse
import sys

from .utils import Workspace



def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cvtitan", description="TITAN CV — evidence-based CVs and autonomous job applications.")
    p.add_argument("--root", help="Workspace folder (default: the project folder or CVTITAN_HOME).")
    p.add_argument("--lang", choices=i18n.available(), help="Message language (default: CVTITAN_LANG or es).")
    sub = p.add_subparsers(dest="cmd", required=True)

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
