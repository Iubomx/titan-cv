"""Comandos del flujo de CV adaptado: validate, import-cv, analyze, match, approve, generate, render, audit,
interview, run, jobs y track (movidos desde `cli.py`; comportamiento sin cambios)."""
from __future__ import annotations

from pathlib import Path

from .. import cv_writer, evidence, importer, interview, job_intel, recruiter
from ..db import DB, STATUSES
from ..profile import Profile
from ..i18n import t
from ..utils import dump_yaml, load_yaml, write_text
from ._common import CliError, _ctx, _load_job, _load_match, _profile, _read_job_text

MIN_SCORE_TO_GENERATE = 30.0


def cmd_validate(args):
    ws, tax = _ctx(args)
    profile = Profile.load(ws.profile_path, tax)
    errors, warnings = profile.validate()
    for e in errors:
        print(f"{t('cli.label_error')}  {e}")
    for w in warnings:
        print(f"{t('cli.label_warning')}  {w}")
    backed = len(profile.backed_keys())
    print(f"\nBacked skills: {backed} / {len(profile.skill_map)} · "
          f"Total experience: {profile.years_experience()} years")
    print("Profile is valid." if not errors else "Profile has errors.")
    return 1 if errors else 0


def cmd_import_cv(args):
    ws, tax = _ctx(args)
    path = Path(args.path)
    text = importer.extract_text(path)
    draft = importer.draft_profile(text, tax, source=path.name)
    out = ws.root / "candidate" / "profile.draft.yaml"
    dump_yaml(draft, out)
    print(f"Borrador creado: {out}")
    exps = draft["experience"]
    print(f"Detected experiences: {len(exps)} · achievements to review: {sum(len(e['achievements']) for e in exps)}")
    print(f"Detected skills (unbacked): {len(draft['detected_skills'])}")
    print("Next step: validate with the candidate and move the data into candidate/profile.yaml.")


def cmd_analyze(args):
    ws, tax = _ctx(args)
    text, meta = _read_job_text(args)
    job = job_intel.analyze(text, tax, title=meta["title"], company=meta["company"], url=meta["url"], job_id=args.id)
    d = ws.job_dir(job["job_id"])
    write_text(d / "raw.txt", text)
    dump_yaml(job, d / "job.yaml")
    write_text(d / "job.md", job_intel.to_markdown(job))
    print(f"Vacante analizada: {job['job_id']}")
    print(f"  {len(job['skills'])} skills · seniority={job['seniority']} · years={job['years_required']}")
    print(f"  {d / 'job.md'}")
    return job


def cmd_match(args, job_id=None):
    ws, tax = _ctx(args)
    job_id = job_id or args.job_id
    profile = _profile(ws, tax)
    job = _load_job(ws, job_id)
    m = evidence.match(job, profile, tax)
    out = ws.out_dir(job_id)
    dump_yaml(m, out / "match.yaml")
    write_text(out / "match.md", evidence.to_markdown(job, m))
    print(f"Evidence score: {m['score']}/100 (potential {m['potential_score']}) · {m['recommendation']}")
    print(f"  {out / 'match.md'}")
    return m


def cmd_approve(args):
    ws, _ = _ctx(args)
    m = _load_match(ws, args.job_id)
    m["approved"] = True
    dump_yaml(m, ws.out_dir(args.job_id) / "match.yaml")
    print(f"Matching for {args.job_id} approved.")


def _render_and_audit(ws, tax, profile, job, m, draft, pdf: bool) -> int:
    out = ws.out_dir(job["job_id"])
    write_text(out / "cv.md", cv_writer.render_markdown(draft))
    docx = cv_writer.render_docx(draft, out / "cv.docx")
    print(f"CV: {docx}")
    if pdf:
        pdf_path = cv_writer.try_pdf(docx)
        print(f"PDF: {pdf_path}" if pdf_path else
              "PDF not generated: install `pip install docx2pdf` (requires Microsoft Word) or export from Word.")
    a = recruiter.audit(draft, job, m, profile, tax)
    dump_yaml(a, out / "audit.yaml")
    write_text(out / "audit.md", recruiter.to_markdown(job, a))
    s = a["scores"]
    print(f"Audit: {'APPROVED' if a['passed'] else 'BLOCKED'} · integrity {s['integrity']} · "
          f"keywords {s['keyword_coverage']} · clarity {s['clarity']}")
    print(f"  {out / 'audit.md'}")
    return 0 if a["passed"] else 1


def cmd_generate(args, job_id=None):
    ws, tax = _ctx(args)
    job_id = job_id or args.job_id
    profile = _profile(ws, tax)
    job, m = _load_job(ws, job_id), _load_match(ws, job_id)
    if not m.get("approved") and not args.force:
        raise CliError(f"Matching is not approved. Review match.md and run `cvtitan approve {job_id}` "
                       "(o usa --force).")
    draft = cv_writer.build_draft(job, m, profile, tax, max_bullets=args.max_bullets)
    dump_yaml(draft, ws.out_dir(job_id) / "cv_draft.yaml")
    return _render_and_audit(ws, tax, profile, job, m, draft, args.pdf)


def cmd_render(args):
    ws, tax = _ctx(args)
    profile = _profile(ws, tax)
    job, m = _load_job(ws, args.job_id), _load_match(ws, args.job_id)
    path = ws.out_dir(args.job_id) / "cv_draft.yaml"
    if not path.exists():
        raise CliError(f"No hay borrador. Ejecuta `cvtitan generate {args.job_id}`.")
    return _render_and_audit(ws, tax, profile, job, m, load_yaml(path), args.pdf)


def cmd_audit(args):
    ws, tax = _ctx(args)
    profile = _profile(ws, tax)
    job, m = _load_job(ws, args.job_id), _load_match(ws, args.job_id)
    draft = load_yaml(ws.out_dir(args.job_id) / "cv_draft.yaml")
    a = recruiter.audit(draft, job, m, profile, tax)
    write_text(ws.out_dir(args.job_id) / "audit.md", recruiter.to_markdown(job, a))
    print(recruiter.to_markdown(job, a))
    return 0 if a["passed"] else 1


def cmd_interview(args, job_id=None):
    ws, tax = _ctx(args)
    job_id = job_id or args.job_id
    profile = _profile(ws, tax)
    job, m = _load_job(ws, job_id), _load_match(ws, job_id)
    path = ws.out_dir(job_id) / "interview.md"
    write_text(path, interview.build(job, m, profile))
    print(f"Interview guide: {path}")


def cmd_run(args):
    job = cmd_analyze(args)
    m = cmd_match(args, job["job_id"])
    if m["score"] < MIN_SCORE_TO_GENERATE and not args.force:
        print(f"\nScore {m['score']} < {MIN_SCORE_TO_GENERATE}: no CV generated. Use --force to apply anyway.")
        return 0
    ws, _ = _ctx(args)
    m["approved"] = True
    dump_yaml(m, ws.out_dir(job["job_id"]) / "match.yaml")
    args.force = True
    rc = cmd_generate(args, job["job_id"])
    cmd_interview(args, job["job_id"])
    db = DB(ws.db_path)
    if not db.get(job["job_id"]):
        s = job.get("salary") or {}
        db.upsert(job["job_id"], url=job.get("url"), company=job.get("company"), title=job["title"],
                  country=job.get("country"), modality=job.get("modality"), score=m["score"],
                  required_coverage=m["required_coverage"], salary_text=job_intel.format_salary(s) or None,
                  status="awaiting_review", status_detail="CV generated from the CLI; apply manually.")
    return rc


def cmd_jobs(args):
    ws, _ = _ctx(args)
    if not ws.jobs_root.exists():
        print("No hay vacantes analizadas.")
        return
    for d in sorted(ws.jobs_root.iterdir()):
        if not (d / "job.yaml").exists():
            continue
        job = load_yaml(d / "job.yaml")
        mp = ws.out_dir(d.name) / "match.yaml"
        score = load_yaml(mp).get("score") if mp.exists() else "—"
        print(f"{d.name:55} score={score!s:>5}  {job.get('company') or ''}")


def cmd_track(args):
    ws, _ = _ctx(args)
    db = DB(ws.db_path)
    if args.action in ("add", "update"):
        if not args.job_id or not args.status:
            raise CliError("Uso: cvtitan track add|update <job_id> --status <estado> [--notes ...]")
        if not db.get(args.job_id):
            info = {}
            jp = ws.job_dir(args.job_id) / "job.yaml"
            if jp.exists():
                job = load_yaml(jp)
                info = {"company": job.get("company"), "title": job.get("title"), "url": job.get("url"),
                        "country": job.get("country"), "modality": job.get("modality")}
            mp = ws.out_dir(args.job_id) / "match.yaml"
            if mp.exists():
                info["score"] = load_yaml(mp).get("score")
            db.upsert(args.job_id, **info)
        row = db.set_status(args.job_id, args.status, args.notes)
        print(f"{row['job_id']}: {row['status_label']}")
    elif args.action == "list":
        for r in db.list():
            print(f"{r['job_id']:50} {r['status_label']:22} {str(r.get('country') or '-'):12} "
                  f"score={r.get('score') if r.get('score') is not None else '-'!s:>5} {(r.get('applied_at') or '')[:10]}")
    else:
        s = db.stats()
        print(f"Postulaciones: {s['total']} (enviadas {s['sent']})")
        print(f"Por estado: {s['by_status']}")
        print(f"By country: {s['by_country']} · by work mode: {s['by_modality']}")
        print(f"Progress rate (screening or beyond): {s['response_rate']}%")
        print(f"Average score of advancing ones: {s['avg_score_advanced']} · of the rest: {s['avg_score_not_advanced']}")


def register(sub) -> None:
    sub.add_parser("validate", help="Validate the candidate profile.").set_defaults(func=cmd_validate)

    s = sub.add_parser("import-cv", help="Extract a draft profile from a PDF/DOCX/TXT.")
    s.add_argument("path")
    s.set_defaults(func=cmd_import_cv)

    def job_source(sp):
        sp.add_argument("--url")
        sp.add_argument("--file")
        sp.add_argument("--text")
        sp.add_argument("--title")
        sp.add_argument("--company")
        sp.add_argument("--id", help="Manual job ID.")

    s = sub.add_parser("analyze", help="01 Job Intelligence: analyze a job posting.")
    job_source(s)
    s.set_defaults(func=cmd_analyze)

    for name, func, hlp in (("match", cmd_match, "02 Evidence: fit matrix."),
                            ("approve", cmd_approve, "Approve the matching to generate a CV."),
                            ("audit", cmd_audit, "04 Recruiter: audit the current CV."),
                            ("interview", cmd_interview, "Generate an interview guide.")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("job_id")
        s.set_defaults(func=func)

    s = sub.add_parser("generate", help="03 CV Optimization: generate draft, DOCX and audit.")
    s.add_argument("job_id")
    s.add_argument("--force", action="store_true")
    s.add_argument("--pdf", action="store_true")
    s.add_argument("--max-bullets", type=int, default=5)
    s.set_defaults(func=cmd_generate)

    s = sub.add_parser("render", help="Re-render and audit cv_draft.yaml after editing.")
    s.add_argument("job_id")
    s.add_argument("--pdf", action="store_true")
    s.set_defaults(func=cmd_render)

    s = sub.add_parser("run", help="Full pipeline: analyze, match, generate, audit and interview.")
    job_source(s)
    s.add_argument("--force", action="store_true")
    s.add_argument("--pdf", action="store_true")
    s.add_argument("--max-bullets", type=int, default=5)
    s.set_defaults(func=cmd_run)

    sub.add_parser("jobs", help="List analyzed jobs.").set_defaults(func=cmd_jobs)

    s = sub.add_parser("track", help="Application tracking.")
    s.add_argument("action", choices=["add", "update", "list", "stats"])
    s.add_argument("job_id", nargs="?")
    s.add_argument("--status", choices=STATUSES)
    s.add_argument("--notes")
    s.set_defaults(func=cmd_track)
