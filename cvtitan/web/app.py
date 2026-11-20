"""Servidor web local de CV TITAN (solo escucha en 127.0.0.1)."""
from __future__ import annotations

import re
import secrets
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from .. import llm
from ..apply.platforms import detect, login_targets
from ..db import PROCESS_STATUSES, STATUS_LABELS
from ..engine import Engine
from ..profile import Profile
from ..taxonomy import Taxonomy
from ..utils import Workspace, load_yaml, slugify
from . import guard

STATIC = Path(__file__).parent / "static"
SERVABLE = {".pdf", ".docx", ".md", ".png", ".html", ".yaml"}


def create_app(ws: Workspace, headless: bool = False, start_runner: bool = True) -> FastAPI:
    engine = Engine(ws)
    db = engine.db
    runner = None
    if start_runner:
        from ..apply.runner import Runner
        runner = Runner(engine, headless=headless)
        runner.start()
        runner.ready.wait(30)

    app = FastAPI(title="CV TITAN", docs_url=None, redoc_url=None)
    app.state.engine, app.state.runner = engine, runner
    app.state.token = secrets.token_urlsafe(24)          # anti-CSRF: solo se entrega dentro de la página principal
    guard.install(app, app.state.token)

    def need(job_id: str) -> dict:
        row = db.get(job_id)
        if not row:
            raise HTTPException(404, "Postulación no encontrada")
        return row

    def send(cmd: str, arg=None, **kw):
        if runner is None:
            raise HTTPException(503, "El robot del navegador no está activo.")
        runner.send(cmd, arg, **kw)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return guard.inject_token((STATIC / "index.html").read_text(encoding="utf-8"), app.state.token)

    @app.get("/api/health")
    def health():
        try:
            tax = Taxonomy.load(ws.taxonomy_path)
            profile = Profile.load(ws.profile_path, tax)
            errors, warnings = profile.validate()
            prof = {"ok": not errors, "errors": errors, "warnings": warnings[:10],
                    "name": (profile.data.get("personal") or {}).get("name"),
                    "example": "example.com" in str((profile.data.get("personal") or {}).get("email", "")),
                    "backed": len(profile.backed_keys())}
        except FileNotFoundError as e:
            prof = {"ok": False, "errors": [str(e)], "warnings": []}
        return {"llm": llm.available(), "model": llm.MODEL, "profile": prof, "runner": runner is not None,
                "platforms": login_targets(), "statuses": STATUS_LABELS, "process_statuses": PROCESS_STATUSES}

    @app.post("/api/settings/apikey")
    def set_key(key: str = Body(..., embed=True)):
        key = key.strip()
        if not re.fullmatch(r"sk-ant-[A-Za-z0-9_\-]{20,}", key):
            raise HTTPException(400, "La clave debe empezar con sk-ant-.")
        env = ws.root / ".env"
        lines = [l for l in (env.read_text(encoding="utf-8").splitlines() if env.exists() else [])
                 if not l.startswith("ANTHROPIC_API_KEY=")]
        env.write_text("\n".join(lines + [f"ANTHROPIC_API_KEY={key}"]) + "\n", encoding="utf-8")
        import os
        os.environ["ANTHROPIC_API_KEY"] = key
        return {"ok": True}

    @app.post("/api/apply")
    def apply(url: str = Body(..., embed=True), force: bool = Body(False, embed=True)):
        url = url.strip()
        if not re.match(r"^https?://", url):
            raise HTTPException(400, "Pega el enlace completo de la vacante (https://...).")
        prev = db.find_by_url(url)
        if prev and prev["status"] in PROCESS_STATUSES:
            raise HTTPException(409, f"Ya postulaste a esta vacante ({(prev.get('applied_at') or '')[:10]}).")
        if prev and prev["status"] not in ("error", "cancelled", "skipped"):
            return {"job_id": prev["job_id"], "existing": True}
        if prev:
            job_id = prev["job_id"]
        else:
            u = urlparse(url)
            host = (u.hostname or "").replace("www.", "").split(".")[0]
            tail = [p for p in u.path.split("/") if p][-1:] or [""]
            base = f"{date.today():%Y%m%d}-{slugify(host + '-' + tail[0], 50)}"
            job_id, n = base, 2
            while db.get(job_id):
                job_id, n = f"{base}-{n}", n + 1
        db.upsert(job_id, url=url, platform=detect(url).key, title=None, status="queued")
        db.event(job_id, "info", "Postulación en cola.")
        send("start", job_id, force=force)
        return {"job_id": job_id}

    @app.get("/api/applications")
    def applications(status: str | None = None, search: str | None = None):
        rows = db.list(status=status or None, search=search or None)
        for r in rows:
            data = r.pop("data", {}) or {}
            r["questions"] = len(data.get("questions") or []) if r["status"] == "needs_input" else 0
            r["has_pdf"] = bool((data.get("files") or {}).get("pdf"))
        return rows

    @app.get("/api/applications/{job_id}")
    def application(job_id: str):
        row = need(job_id)
        row["events"] = db.events(job_id)[-60:]
        out = ws.out_dir(job_id)
        row["files"] = sorted(p.name for p in out.iterdir() if p.suffix in SERVABLE) if out.exists() else []
        mp = out / "match.yaml"
        if mp.exists():
            m = load_yaml(mp)
            row["match"] = {"rows": [{k: r[k] for k in ("name", "importance", "status")} for r in m["rows"]],
                            "recommendation": m.get("recommendation"), "years": m.get("years")}
        return row

    @app.post("/api/applications/{job_id}/resume")
    def resume(job_id: str, answers: dict = Body(default={}, embed=True), remember: bool = Body(True, embed=True)):
        need(job_id)
        db.set_status(job_id, "filling", "Continuando…")
        send("resume", job_id, answers=answers, remember=remember)
        return {"ok": True}

    @app.post("/api/applications/{job_id}/submit")
    def submit(job_id: str):
        row = need(job_id)
        if row["status"] != "awaiting_review":
            raise HTTPException(409, "Solo se puede enviar una postulación lista para revisar.")
        db.event(job_id, "info", "Envío confirmado por el candidato.")
        send("submit", job_id)
        return {"ok": True}

    @app.post("/api/applications/{job_id}/retry")
    def retry(job_id: str, force: bool = Body(False, embed=True)):
        need(job_id)
        db.set_status(job_id, "queued", "Reintentando" + (" (forzada)" if force else ""))
        send("start", job_id, force=force)
        return {"ok": True}

    @app.post("/api/applications/{job_id}/status")
    def set_status(job_id: str, status: str = Body(..., embed=True), notes: str | None = Body(None, embed=True)):
        need(job_id)
        if status not in STATUS_LABELS:
            raise HTTPException(400, "Estado inválido")
        db.set_status(job_id, status, "Actualizado manualmente")
        if notes is not None:
            db.upsert(job_id, notes=notes)
        if status in ("applied", "cancelled") and runner:
            runner.send("close", job_id)
        return db.get(job_id)

    @app.patch("/api/applications/{job_id}")
    def patch(job_id: str, fields: dict = Body(...)):
        need(job_id)
        allowed = {"notes", "salary_expectation", "country", "city", "modality", "company", "title", "salary_text"}
        clean = {k: v for k, v in fields.items() if k in allowed}
        return db.upsert(job_id, **clean)

    @app.delete("/api/applications/{job_id}")
    def delete(job_id: str):
        need(job_id)
        if runner:
            runner.send("close", job_id)
        db.delete(job_id)
        return {"ok": True}

    @app.get("/api/files/{job_id}/{name}")
    def file(job_id: str, name: str):
        out = ws.out_dir(job_id).resolve()
        path = (out / name).resolve()
        if path.parent != out or path.suffix not in SERVABLE or not path.exists():
            raise HTTPException(404, "Archivo no encontrado")
        return FileResponse(path)

    @app.post("/api/browser/open")
    def open_browser(url: str = Body(..., embed=True)):
        if not re.match(r"^https?://", url):
            raise HTTPException(400, "URL inválida")
        send("open", url)
        return {"ok": True}

    @app.get("/api/stats")
    def stats():
        return db.stats()

    @app.get("/api/export.csv", response_class=PlainTextResponse)
    def export():
        return PlainTextResponse("﻿" + db.export_csv(), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=postulaciones.csv"})

    @app.on_event("shutdown")
    def shutdown():
        if runner:
            runner.send("stop")

    return app
