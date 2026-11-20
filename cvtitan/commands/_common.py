"""Piezas compartidas por los módulos de `cvtitan.commands` (evita importar `cli` y crear ciclos)."""
from __future__ import annotations

import sys
from pathlib import Path

from .. import job_intel
from ..profile import Profile
from ..taxonomy import Taxonomy
from ..utils import Workspace, load_yaml


class CliError(Exception):
    """Error esperado de un comando: `main()` lo imprime como `Error: ...` y devuelve el código 2."""


# ---------------------------------------------------------------------- helpers compartidos
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
