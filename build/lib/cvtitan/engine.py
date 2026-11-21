"""Orquestación sin navegador: vacante -> análisis -> matching -> CV -> auditoría -> historial."""
from __future__ import annotations

from pathlib import Path

from . import cv_writer, evidence, interview, job_intel, llm, recruiter
from .apply.platforms import detect
from .db import DB
from .profile import Profile
from .taxonomy import Taxonomy
from .utils import Workspace, dump_yaml, load_yaml, numbers_in, slugify, write_text


class EngineError(Exception):
    pass


class Engine:
    def __init__(self, ws: Workspace, db: DB | None = None):
        self.ws = ws
        llm.load_env(ws.root)
        self.db = db or DB(ws.db_path)
        self.settings = load_yaml(ws.settings_path) if ws.settings_path.exists() else {}
        import os
        os.environ["CVTITAN_LLM_ENABLED"] = "1" if (self.settings.get("llm") or {}).get("enabled") else "0"
        os.environ["CVTITAN_LLM_SEND_CONTACT"] = "1" if (self.settings.get("llm") or {}).get("send_contact") else "0"
        from . import llm_privacy
        llm_privacy.set_audit_path(ws.root / "data" / "llm_audit.jsonl")

    def load(self) -> tuple[Taxonomy, Profile]:
        """Se recarga en cada postulación para tomar cambios recientes del perfil."""
        tax = Taxonomy.load(self.ws.taxonomy_path)
        profile = Profile.load(self.ws.profile_path, tax)
        errors, _ = profile.validate()
        if errors:
            raise EngineError("El perfil tiene errores: " + "; ".join(errors))
        return tax, profile

    # ------------------------------------------------------------------ análisis
    def new_job_id(self, title: str | None, company: str | None, url: str) -> str:
        from datetime import date
        base = f"{date.today():%Y%m%d}-" + slugify(" ".join(filter(None, [company, title])) or url, 50)
        job_id, n = base, 2
        while self.db.get(job_id) and self.db.get(job_id).get("url") != url:
            job_id, n = f"{base}-{n}", n + 1
        return job_id

    def analyze(self, job_id: str, url: str, raw: dict) -> tuple[dict, dict]:
        """raw = {text, title, company, country?, city?, salary_*?} (de parse_html)."""
        tax, profile = self.load()
        log = lambda m: self.db.event(job_id, "info", m)  # noqa: E731
        job = job_intel.analyze(raw["text"], tax, title=raw.get("title"), company=raw.get("company"),
                                url=url, job_id=job_id, meta=raw)
        if llm.available():
            try:
                facts = llm.extract_job(raw["text"][:60000], url)
                job = job_intel.enrich(job, facts, tax)
                log("Vacante analizada con IA.")
            except llm.LLMUnavailable as e:
                log(f"IA no disponible para analizar la vacante ({e}); uso análisis heurístico.")
        else:
            log("Sin API key: análisis heurístico.")

        d = self.ws.job_dir(job_id)
        write_text(d / "raw.txt", raw["text"])
        dump_yaml(job, d / "job.yaml")
        write_text(d / "job.md", job_intel.to_markdown(job))

        m = evidence.match(job, profile, tax)
        out = self.ws.out_dir(job_id)
        dump_yaml(m, out / "match.yaml")
        write_text(out / "match.md", evidence.to_markdown(job, m))

        s = job.get("salary") or {}
        self.db.upsert(
            job_id, url=url, platform=detect(url).key, company=job.get("company"), title=job.get("title"),
            country=job.get("country"), city=job.get("city"), modality=job.get("modality"),
            seniority=job.get("seniority"), salary_text=job_intel.format_salary(s) or None,
            salary_min=s.get("salary_min"), salary_max=s.get("salary_max"),
            salary_currency=s.get("salary_currency"), salary_period=s.get("salary_period"),
            score=m["score"], required_coverage=m["required_coverage"],
            skills_backed=[r["name"] for r in m["rows"] if r["status"] == "backed"],
            skills_gap=[r["name"] for r in m["rows"] if r["status"] != "backed" and r["importance"] == "required"],
        )
        log(f"Compatibilidad {m['score']}/100 · obligatorios cubiertos {m['required_coverage']}%.")
        return job, m

    # ------------------------------------------------------------------ CV
    def generate(self, job_id: str, pw=None) -> dict:
        tax, profile = self.load()
        job = load_yaml(self.ws.job_dir(job_id) / "job.yaml")
        m = load_yaml(self.ws.out_dir(job_id) / "match.yaml")
        m["approved"] = True
        out = self.ws.out_dir(job_id)
        dump_yaml(m, out / "match.yaml")

        draft = cv_writer.build_draft(job, m, profile, tax)
        if llm.available():
            try:
                rw = llm.rewrite_cv(draft, job, [profile.skill_map[k]["name"] for k in profile.backed_keys()])
                draft, rejected = cv_writer.apply_rewrites(draft, rw, profile, tax)
                msg = "CV adaptado con IA."
                if rejected:
                    msg += f" {len(rejected)} bloque(s) volvieron al texto original por no pasar la auditoría."
                self.db.event(job_id, "info", msg)
            except llm.LLMUnavailable as e:
                self.db.event(job_id, "info", f"IA no disponible para redactar ({e}); CV con textos del perfil.")

        dump_yaml(draft, out / "cv_draft.yaml")
        a = recruiter.audit(draft, job, m, profile, tax)
        dump_yaml(a, out / "audit.yaml")
        write_text(out / "audit.md", recruiter.to_markdown(job, a))
        if not a["passed"]:
            raise EngineError("La auditoría bloqueó el CV; revisa audit.md.")

        files = {"docx": str(cv_writer.render_docx(draft, out / "cv.docx"))}
        write_text(out / "cv.md", cv_writer.render_markdown(draft))
        html = cv_writer.render_html(draft)
        write_text(out / "cv.html", html)
        name = slugify((draft["personal"].get("name") or "CV"), 40).replace("-", "_")
        pdf = cv_writer.html_to_pdf(html, out / f"CV_{name}.pdf",
                                    channel=(self.settings.get("browser") or {}).get("channel", "chrome"), pw=pw)
        files["pdf"] = str(pdf) if pdf else None
        files["cv"] = files["pdf"] or files["docx"]
        files.update(self.choose_cv(job, profile, files["cv"]))
        write_text(out / "interview.md", interview.build(job, m, profile))
        self.db.update_data(job_id, files=files, audit=a["scores"])
        self.db.event(job_id, "info", f"CV generado ({'PDF' if pdf else 'DOCX'}) · integridad "
                                      f"{a['scores']['integrity']} · keywords {a['scores']['keyword_coverage']}.")
        return files

    def choose_cv(self, job: dict, profile, adapted: str | None) -> dict:
        """Qué CV se adjunta. El CV adaptado se genera en español (idioma del perfil); para avisos en otro
        idioma se usa tu CV original de ese idioma (profile.cv_files). settings.cv_mode = original fuerza
        siempre el original."""
        lang = job.get("language") or job_intel.detect_language(
            (self.ws.job_dir(job["job_id"]) / "raw.txt").read_text(encoding="utf-8")
            if (self.ws.job_dir(job["job_id"]) / "raw.txt").exists() else "")
        originals = {k: self.ws.root / v for k, v in (profile.data.get("cv_files") or {}).items() if v}
        mode = self.settings.get("cv_mode", "adaptado")
        original = originals.get(lang)
        if original and original.exists() and (lang != "es" or mode == "original" or not adapted):
            kind = "original"
            cv = str(original)
        elif lang != "es" and originals.get("en") and originals["en"].exists():
            kind, cv = "original", str(originals["en"])     # sin CV en ese idioma: inglés como lengua franca
            lang = "en"
        else:
            kind, cv = "adaptado", adapted
        self.db.event(job["job_id"], "info", f"CV a adjuntar: {kind} ({lang}) · {Path(cv).name if cv else '—'}")
        return {"cv": cv, "cv_lang": lang, "cv_kind": kind}

    def cover_letter(self, job_id: str, pw=None) -> str | None:
        """Carta trazable: solo se acepta si no trae cifras ni skills ajenas al perfil."""
        out = self.ws.out_dir(job_id)
        existing = (self.db.get(job_id) or {}).get("data", {}).get("files", {}).get("cover_letter")
        if existing and Path(existing).exists():
            return existing
        if not llm.available():
            return None
        tax, profile = self.load()
        job = load_yaml(self.ws.job_dir(job_id) / "job.yaml")
        context = {k: profile.data.get(k) for k in ("personal", "summary", "experience", "projects", "education")}
        context["skills_respaldadas"] = [profile.skill_map[k]["name"] for k in profile.backed_keys()]
        try:
            text = llm.cover_letter(job, context)
        except llm.LLMUnavailable:
            return None
        profile_text = " ".join(str(v) for v in context.values())
        bad_numbers = numbers_in(text) - numbers_in(profile_text)
        bad_skills = [k for k in tax.find_in(text) if not profile.is_backed(k) and k not in tax.find_in(profile_text)]
        if bad_numbers or bad_skills:
            self.db.event(job_id, "warning", "Carta de presentación descartada por incluir datos no respaldados.")
            return None
        write_text(out / "cover_letter.md", text)
        from html import escape
        html = ("<!doctype html><html><head><meta charset='utf-8'><style>@page{size:A4;margin:22mm}"
                "body{font-family:Calibri,Arial,sans-serif;font-size:11pt;line-height:1.45}</style></head><body>"
                + "".join(f"<p>{escape(p)}</p>" for p in text.split("\n") if p.strip()) + "</body></html>")
        pdf = cv_writer.html_to_pdf(html, out / "Carta_presentacion.pdf", pw=pw)
        if pdf:
            files = (self.db.get(job_id) or {}).get("data", {}).get("files", {})
            files["cover_letter"] = str(pdf)
            self.db.update_data(job_id, files=files)
            return str(pdf)
        return None
