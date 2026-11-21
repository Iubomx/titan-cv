"""`cvtitan llmlog`: qué se envió a la API de Claude (solo metadatos; nunca el contenido)."""
from __future__ import annotations

from ..utils import Workspace


def register(sub) -> None:
    s = sub.add_parser("llmlog", help="Show the local audit log of AI requests (metadata only, never content).")
    s.add_argument("--tail", type=int, default=20, help="Last N requests (default 20).")
    s.set_defaults(func=run)


def run(args) -> int:
    from ..llm_privacy import read
    ws = Workspace.resolve(args.root)
    rows = read(ws.root / "data" / "llm_audit.jsonl", tail=args.tail)
    if not rows:
        print("No AI requests recorded (the AI is off by default: config/settings.yaml -> llm.enabled).")
        return 0
    for r in rows:
        contact = "contact: YES" if r.get("send_contact") else "contact: no"
        print(f"{r.get('ts', '?')}  {r.get('purpose', '?'):<14} {r.get('model', '?')}  "
              f"in/out tokens: {r.get('input_tokens')}/{r.get('output_tokens')}  {contact}  "
              f"sent: {', '.join(r.get('sent') or [])}")
    print(f"\n{len(rows)} request(s) shown. Content is never stored. Delete the log with `cvtitan purge --historial`.")
    return 0
