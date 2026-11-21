"""`cvtitan preview <job_id>`: vista previa HTML del CV adaptado con el diff contra tu perfil."""
from __future__ import annotations

from ..utils import Workspace, load_yaml
from ._common import CliError


def register(sub) -> None:
    s = sub.add_parser("preview", help="HTML preview of the tailored CV with a diff against your profile.")
    s.add_argument("job_id")
    s.add_argument("--open", action="store_true", help="Open the preview in your browser.")
    s.set_defaults(func=run)


def run(args) -> int:
    from ..cv_diff import diff_draft, preview_html, summarize
    from ..profile import Profile
    from ..taxonomy import Taxonomy

    ws = Workspace.resolve(args.root)
    draft_path = ws.out_dir(args.job_id) / "cv_draft.yaml"
    if not draft_path.exists():
        raise CliError(f"No draft for '{args.job_id}'. Run `cvtitan generate {args.job_id}` first.")
    profile = Profile.load(ws.profile_path, Taxonomy.load(ws.taxonomy_path))
    draft = load_yaml(draft_path)
    changes = diff_draft(draft, profile)
    out = ws.out_dir(args.job_id) / "cv_preview.html"
    out.write_text(preview_html(draft, changes), encoding="utf-8")
    s = summarize(changes)
    print(f"Preview: {out}")
    print(f"{s['edited']} edited · {s['unchanged']} identical to your profile · {s['unknown_source']} without source · "
          f"{s['with_new_numbers']} with new numbers")
    if s["unknown_source"] or s["with_new_numbers"]:
        print("Review the highlighted blocks: new numbers or missing sources can fail the audit.")
    if args.open:
        import webbrowser
        webbrowser.open(out.as_uri())
    return 0
