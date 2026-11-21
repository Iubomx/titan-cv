"""03 — CV Optimization Agent: arma un borrador trazable y lo renderiza a DOCX/Markdown/PDF."""
from __future__ import annotations

from pathlib import Path

from .profile import Profile
from .taxonomy import Taxonomy
from .utils import now_iso

MAX_SKILLS = 16
MAX_PROJECTS = 3

HEADINGS = {
    "summary": "Perfil profesional",
    "skills": "Habilidades técnicas",
    "experience": "Experiencia profesional",
    "projects": "Proyectos",
    "education": "Educación",
    "certifications": "Certificaciones",
    "languages": "Idiomas",
}


def build_draft(job: dict, m: dict, profile: Profile, taxonomy: Taxonomy, max_bullets: int = 5) -> dict:
    weights = {s["key"]: s["weight"] for s in job["skills"]}
    d = profile.data

    def relevance(ev_id: str) -> float:
        return sum(weights.get(k, 0.0) for k in profile.evidence_skill_keys(ev_id))

    # Resumen: la variante cuyo foco pese más para esta vacante.
    summary_src, summary_text, best = "summary", d.get("summary", ""), -1.0
    for v in d.get("summary_variants") or []:
        focus = sum(weights.get(taxonomy.key_for(f, register=False), 0.0) for f in v.get("focus") or [])
        if focus > best and focus > 0:
            best, summary_src, summary_text = focus, f"summary:{v['id']}", v["text"]

    # Skills: solo respaldadas; primero las que pide la vacante.
    backed = profile.backed_keys()
    ordered = sorted(backed, key=lambda k: (-weights.get(k, 0.0), list(profile.skill_map).index(k)))
    skills = [profile.skill_map[k]["name"] for k in ordered[:MAX_SKILLS]]

    experience = []
    for exp in d.get("experience") or []:
        achs = exp.get("achievements") or []
        ranked = sorted(enumerate(achs), key=lambda t: (-relevance(t[1]["id"]), t[0]))
        relevant = [a for _, a in ranked if relevance(a["id"]) > 0][:max_bullets]
        chosen = relevant if len(relevant) >= 2 else [a for _, a in ranked[:max(2, len(relevant))]]
        experience.append({
            "source": exp["id"],
            "role": exp.get("role"),
            "company": exp.get("company"),
            "location": exp.get("location"),
            "start": str(exp.get("start") or ""),
            "end": str(exp.get("end") or "Presente"),
            "bullets": [{"text": a["text"], "source": a["id"]} for a in chosen],
        })

    projects = []
    scored_projects = sorted(
        (p for p in d.get("projects") or [] if p.get("status", "completed") == "completed"),
        key=lambda p: -relevance(p["id"]),
    )
    for p in scored_projects[:MAX_PROJECTS]:
        if relevance(p["id"]) <= 0:
            continue
        projects.append({"source": p["id"], "name": p.get("name"),
                         "text": p.get("description", ""), "url": p.get("url")})

    return {
        "meta": {"job_id": job["job_id"], "target": f"{job['title']} — {job.get('company') or ''}".strip(" —"),
                 "generated_at": now_iso(), "match_score": m["score"],
                 "editable": "Puedes reescribir textos, pero cada bloque debe conservar su `source` "
                             "y no agregar cifras ni tecnologías ausentes en la fuente. "
                             "Luego ejecuta `cvtitan render <job_id>`."},
        "personal": d.get("personal") or {},
        "headline": (d.get("personal") or {}).get("headline", ""),
        "summary": {"text": summary_text, "source": summary_src},
        "skills": skills,
        "experience": experience,
        "projects": projects,
        "education": [{"source": e["id"], "text": " — ".join(filter(None, [
            e.get("degree"), e.get("institution"), str(e.get("year") or "")]))}
            for e in d.get("education") or []],
        "certifications": [{"source": c["id"], "text": " — ".join(filter(None, [
            c.get("name"), c.get("issuer"), str(c.get("year") or "")]))}
            for c in d.get("certifications") or []],
        "languages": [f"{l['name']}: {l.get('level', '')}".strip(": ") for l in d.get("languages") or []],
    }


def _contact_line(personal: dict) -> str:
    return " | ".join(str(personal[k]) for k in ("email", "phone", "location", "linkedin", "github", "website")
                      if personal.get(k))


def _dates(item: dict) -> str:
    return " – ".join(filter(None, [item.get("start"), item.get("end")]))


def render_markdown(draft: dict) -> str:
    p = draft["personal"]
    out = [f"# {p.get('name', '')}", ""]
    if draft.get("headline"):
        out += [f"**{draft['headline']}**", ""]
    out += [_contact_line(p), "", f"## {HEADINGS['summary']}", "", draft["summary"]["text"].strip(), ""]
    if draft["skills"]:
        out += [f"## {HEADINGS['skills']}", "", ", ".join(draft["skills"]), ""]
    out += [f"## {HEADINGS['experience']}", ""]
    for e in draft["experience"]:
        out += [f"### {e['role']} — {e['company']}",
                f"*{_dates(e)}{' · ' + e['location'] if e.get('location') else ''}*", ""]
        out += [f"- {b['text']}" for b in e["bullets"]] + [""]
    if draft["projects"]:
        out += [f"## {HEADINGS['projects']}", ""]
        out += [f"- **{pr['name']}**: {pr['text']}" + (f" ({pr['url']})" if pr.get("url") else "")
                for pr in draft["projects"]] + [""]
    for section in ("education", "certifications"):
        if draft[section]:
            out += [f"## {HEADINGS[section]}", ""] + [f"- {x['text']}" for x in draft[section]] + [""]
    if draft["languages"]:
        out += [f"## {HEADINGS['languages']}", ""] + [f"- {l}" for l in draft["languages"]] + [""]
    return "\n".join(out)


def render_docx(draft: dict, path: Path) -> Path:
    """DOCX de una columna, sin tablas ni imágenes: lo más legible para un ATS."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    doc = Document()
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Cm(1.8)
        section.left_margin = section.right_margin = Cm(2.0)
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(2)

    def para(text="", bold=False, italic=False, size=None, center=False, style=None, space_before=0):
        p = doc.add_paragraph(style=style)
        if text:
            r = p.add_run(text)
            r.bold, r.italic = bold, italic
            if size:
                r.font.size = Pt(size)
        if center:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(space_before)
        return p

    def heading(text):
        para(text.upper(), bold=True, size=11.5, space_before=10)

    p = draft["personal"]
    para(p.get("name", ""), bold=True, size=18, center=True)
    if draft.get("headline"):
        para(draft["headline"], size=11.5, center=True)
    para(_contact_line(p), size=9.5, center=True)

    heading(HEADINGS["summary"])
    para(draft["summary"]["text"].strip())
    if draft["skills"]:
        heading(HEADINGS["skills"])
        para(", ".join(draft["skills"]))
    heading(HEADINGS["experience"])
    for e in draft["experience"]:
        para(f"{e['role']} — {e['company']}", bold=True, space_before=4)
        para(f"{_dates(e)}{' · ' + e['location'] if e.get('location') else ''}", italic=True, size=9.5)
        for b in e["bullets"]:
            para(b["text"], style="List Bullet")
    if draft["projects"]:
        heading(HEADINGS["projects"])
        for pr in draft["projects"]:
            bp = doc.add_paragraph(style="List Bullet")
            bp.add_run(f"{pr['name']}: ").bold = True
            bp.add_run(pr["text"] + (f" ({pr['url']})" if pr.get("url") else ""))
    for section in ("education", "certifications"):
        if draft[section]:
            heading(HEADINGS[section])
            for x in draft[section]:
                para(x["text"], style="List Bullet")
    if draft["languages"]:
        heading(HEADINGS["languages"])
        para(", ".join(draft["languages"]))

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def apply_rewrites(draft: dict, rewrite, profile: Profile, taxonomy: Taxonomy) -> tuple[dict, list[str]]:
    """Aplica la reescritura del LLM bloque a bloque. Un bloque que rompa una regla de
    integridad (cifra o skill sin respaldo) se descarta y queda el texto original."""
    from .recruiter import check_block

    rejected: list[str] = []

    def ok(text: str, source: str) -> bool:
        return bool(text and text.strip()) and not any(
            level == "error" for level, _, _ in check_block(text, source, profile, taxonomy))

    if ok(rewrite.headline, "headline"):
        draft["headline"] = rewrite.headline.strip()
    elif rewrite.headline:
        rejected.append("headline")
    src = draft["summary"]["source"]
    if ok(rewrite.summary, src):
        draft["summary"]["text"] = rewrite.summary.strip()
    else:
        rejected.append("summary")
    by_source = {r.source: r.text for r in rewrite.bullets}
    for e in draft["experience"]:
        for b in e["bullets"]:
            new = by_source.get(b["source"])
            if new is None:
                continue
            if ok(new, b["source"]):
                b["original"] = b["text"]
                b["text"] = new.strip()
            else:
                rejected.append(b["source"])
    draft["meta"]["rewritten_by"] = "llm"
    draft["meta"]["rejected_rewrites"] = rejected
    return draft, rejected


def render_html(draft: dict) -> str:
    """HTML imprimible de una columna (base del PDF)."""
    from html import escape as esc

    p = draft["personal"]
    parts = [f"<h1>{esc(p.get('name', ''))}</h1>"]
    if draft.get("headline"):
        parts.append(f"<div class='headline'>{esc(draft['headline'])}</div>")
    parts.append(f"<div class='contact'>{esc(_contact_line(p))}</div>")
    parts.append(f"<h2>{HEADINGS['summary']}</h2><p>{esc(draft['summary']['text'].strip())}</p>")
    if draft["skills"]:
        parts.append(f"<h2>{HEADINGS['skills']}</h2><p>{esc(', '.join(draft['skills']))}</p>")
    parts.append(f"<h2>{HEADINGS['experience']}</h2>")
    for e in draft["experience"]:
        where = f" · {esc(e['location'])}" if e.get("location") else ""
        parts.append(f"<div class='job'><b>{esc(e['role'] or '')} — {esc(e['company'] or '')}</b>"
                     f"<div class='dates'>{esc(_dates(e))}{where}</div><ul>"
                     + "".join(f"<li>{esc(b['text'])}</li>" for b in e["bullets"]) + "</ul></div>")
    if draft["projects"]:
        parts.append(f"<h2>{HEADINGS['projects']}</h2><ul>" + "".join(
            f"<li><b>{esc(pr['name'] or '')}:</b> {esc(pr['text'])}"
            + (f" ({esc(pr['url'])})" if pr.get("url") else "") + "</li>" for pr in draft["projects"]) + "</ul>")
    for section in ("education", "certifications"):
        if draft[section]:
            parts.append(f"<h2>{HEADINGS[section]}</h2><ul>"
                         + "".join(f"<li>{esc(x['text'])}</li>" for x in draft[section]) + "</ul>")
    if draft["languages"]:
        parts.append(f"<h2>{HEADINGS['languages']}</h2><p>{esc(', '.join(draft['languages']))}</p>")
    css = """
    @page { size: A4; margin: 16mm 18mm; }
    body { font-family: Calibri, Arial, sans-serif; font-size: 10.5pt; color: #111; line-height: 1.32; }
    h1 { text-align: center; font-size: 20pt; margin: 0; }
    .headline { text-align: center; font-size: 11.5pt; margin-top: 2px; }
    .contact { text-align: center; font-size: 9.5pt; color: #333; margin: 4px 0 6px; }
    h2 { font-size: 11pt; text-transform: uppercase; border-bottom: 1px solid #999; margin: 12px 0 4px; padding-bottom: 1px; }
    p { margin: 2px 0; } ul { margin: 2px 0 4px; padding-left: 16px; } li { margin: 1px 0; }
    .job { margin-top: 6px; } .dates { font-style: italic; font-size: 9.5pt; color: #333; }
    .job, li { break-inside: avoid; }
    """
    return (f"<!doctype html><html lang='es'><head><meta charset='utf-8'><title>{esc(p.get('name', 'CV'))}</title>"
            f"<style>{css}</style></head><body>{''.join(parts)}</body></html>")


def html_to_pdf(html_text: str, pdf_path: Path, channel: str = "chrome", pw=None) -> Path | None:
    """Imprime HTML a PDF con Chrome sin interfaz (Playwright). None si no está disponible.
    `pw`: instancia de Playwright ya abierta en este hilo (la API síncrona no admite anidarse)."""
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    def _print(playwright):
        try:
            browser = playwright.chromium.launch(channel=channel, headless=True)
        except Exception:
            browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html_text, wait_until="load")
            page.pdf(path=str(pdf_path), format="A4", print_background=True)
        finally:
            browser.close()

    try:
        if pw is not None:
            _print(pw)
        else:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                _print(playwright)
    except Exception:
        return None
    return pdf_path if pdf_path.exists() else None


def try_pdf(docx_path: Path) -> Path | None:
    """Convierte a PDF con Microsoft Word (docx2pdf). Devuelve None si no está disponible."""
    try:
        from docx2pdf import convert
    except ImportError:
        return None
    pdf = docx_path.with_suffix(".pdf")
    try:
        convert(str(docx_path), str(pdf))
    except Exception:
        return None
    return pdf if pdf.exists() else None
