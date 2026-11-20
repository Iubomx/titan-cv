"""`cvtitan schema`: imprime o guarda el esquema JSON del perfil para el editor."""
from __future__ import annotations

import json
from pathlib import Path


def register(sub) -> None:
    s = sub.add_parser("schema", help="Write the JSON Schema of candidate/profile.yaml (editor autocompletion).")
    s.add_argument("--out", help="File to write (default: print to the terminal).")
    s.set_defaults(func=run)


def run(args) -> int:
    from ..profile_schema import json_schema
    text = json.dumps(json_schema(), indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"Schema written to {args.out}.")
    else:
        print(text)
    return 0
