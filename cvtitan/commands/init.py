"""`cvtitan init`: crea carpetas y `candidate/profile.yaml` (ejemplo genérico, plantilla por rubro o asistente)."""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from ..utils import PACKAGE_ROOT, Workspace, dump_yaml
from ._common import CliError


def register(sub) -> None:
    s = sub.add_parser("init", help="Create folders and candidate/profile.yaml (example, template or guided).")
    s.add_argument("--plantilla", metavar="NAME", help="Start from a fictitious profile by field (see --listar).")
    s.add_argument("--listar", action="store_true", help="List the available templates and exit.")
    s.add_argument("--guiado", action="store_true", help="Answer a few questions to create a minimal valid profile.")
    s.set_defaults(func=run)


def templates(ws: Workspace) -> dict[str, Path]:
    """Plantillas `candidate/examples/<nombre>.example.yaml` del workspace (o del paquete si no hay locales)."""
    for base in (ws.root / "candidate" / "examples", PACKAGE_ROOT / "candidate" / "examples"):
        found = {p.name.removesuffix(".example.yaml"): p for p in sorted(base.glob("*.example.yaml"))}
        if found:
            return found
    return {}


def _csv(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]


def guided_profile(ask) -> tuple[dict, dict]:
    """(perfil, declaraciones) mínimos y válidos a partir de las respuestas. Nada se inventa: lo vacío queda vacío."""
    personal = {k: v for k, v in {
        "name": ask("Full name: "), "headline": ask("Headline (e.g. Data Analyst | Python, SQL): "),
        "email": ask("Email: "), "phone": ask("Phone: "), "location": ask("City, Country: ")}.items() if v}
    country = ask("Country where you look for work: ")
    prefs = {k: v for k, v in {
        "country": country, "salary_expectation": ask("Salary expectation (e.g. CLP 2.000.000 net/month): "),
        "availability": ask("Availability (e.g. Immediate, 30 days): "), "willing_to_relocate": "No"}.items() if v}
    authorized = _csv(ask("Countries where you can work WITHOUT sponsorship (comma separated): "))
    profile = {"personal": personal, "summary": "", "experience": [], "projects": [], "education": [],
               "certifications": [], "skills": [], "preferences": prefs, "documents": [], "languages": []}
    declarations = {"confirmed_on": date.today().isoformat(),
                    "citizenship": _csv(ask("Citizenship(s) (comma separated): ")),
                    "legal_residence": _csv(ask("Countries of legal residence (comma separated): ")),
                    "work_authorization": authorized, "security_clearance": False,
                    "needs_sponsorship_outside_authorized": True}
    return profile, declarations


def run(args) -> int:
    ws = Workspace.resolve(args.root)
    available = templates(ws)
    if args.listar:
        print("Templates: " + (", ".join(available) or "(none)"))
        return 0
    if args.guiado and args.plantilla:
        raise CliError("Use --guiado or --plantilla, not both.")
    if args.plantilla and args.plantilla not in available:
        raise CliError(f"Unknown template '{args.plantilla}'. Available: {', '.join(available) or '(none)'}.")
    for d in ("candidate", "data/jobs", "data/outputs"):
        (ws.root / d).mkdir(parents=True, exist_ok=True)
    if ws.profile_path.exists():
        print(f"{ws.profile_path} already exists; not overwritten.")
        return 0
    if args.guiado:
        profile, declarations = guided_profile(lambda prompt: input(prompt).strip())
        if not profile["personal"].get("name"):
            raise CliError("The name is required.")
        dump_yaml(profile, ws.profile_path)
        decl_path = ws.root / "candidate" / "declarations.yaml"
        if not decl_path.exists():
            dump_yaml(declarations, decl_path)
        print(f"Created {ws.profile_path} and {decl_path}.\nNext: add your experience as achievements with ids, "
              "then run `cvtitan validate`.")
        return 0
    source = available[args.plantilla] if args.plantilla else ws.example_profile_path
    shutil.copy(source, ws.profile_path)
    print(f"Created {ws.profile_path} from {'the ' + args.plantilla + ' template' if args.plantilla else 'the example'}."
          " Replace it with your real data.")
    return 0
