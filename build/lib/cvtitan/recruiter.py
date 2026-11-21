"""04 — Recruiter Simulation Agent: audita integridad, cobertura y claridad del CV generado."""
from __future__ import annotations

from .profile import Profile
from .taxonomy import Taxonomy
from .utils import normalize, now_iso, numbers_in, word_count

WEAK_STARTS = ["responsable de", "encargado de", "encargada de", "a cargo de", "participe en",
               "ayude a", "apoye", "apoyo en", "trabaje en", "tareas de", "funciones de",
               "responsible for", "helped", "worked on", "assisted"]
MAX_BULLET_WORDS = 40
MAX_SUMMARY_WORDS = 90
MAX_TOTAL_WORDS = 850
MIN_TOTAL_WORDS = 220


def source_texts(profile: Profile) -> dict[str, str]:
    out = {k: v["text"] for k, v in profile.evidence().items()}
    out.update(profile.summary_sources())
    out["headline"] = (profile.data.get("personal") or {}).get("headline", "")
    return out


def check_block(text: str, source: str | None, profile: Profile, taxonomy: Taxonomy) -> list[tuple[str, str, str]]:
    """Reglas de integridad para un bloque: (nivel, código, mensaje)."""
    sources = source_texts(profile)
    if source not in sources:
        return [("error", "SIN_FUENTE", f"El bloque no apunta a una evidencia existente (source={source!r}).")]
    src_text = sources[source]
    issues = []
    invented = numbers_in(text) - numbers_in(src_text)
    if invented:
        issues.append(("error", "METRICA_NO_RESPALDADA",
                       f"Cifras que no están en la fuente `{source}`: {', '.join(sorted(invented))}."))
    ev = profile.evidence()
    src_keys = set(taxonomy.find_in(src_text)) | (profile.evidence_skill_keys(source) if source in ev else set())
    for key in taxonomy.find_in(text):
        if profile.is_backed(key):
            continue
        name = taxonomy.name(key)
        if key in src_keys:
            issues.append(("warning", "SKILL_SOLO_EN_FUENTE",
                           f"'{name}' aparece en la fuente pero no está como skill respaldada en el perfil. "
                           "Valídala y declárala como `backed`."))
        else:
            status = profile.status(key) or "no declarada"
            issues.append(("error", "SKILL_NO_RESPALDADA", f"'{name}' ({status}) no tiene evidencia que la respalde."))
    return issues


def _blocks(draft: dict):
    """(ubicación, texto, source) de cada bloque redactado del CV."""
    if draft.get("headline"):
        yield "headline", draft["headline"], "headline"
    yield "summary", draft["summary"]["text"], draft["summary"].get("source")
    for e in draft["experience"]:
        for i, b in enumerate(e["bullets"], 1):
            yield f"{e['source']}#{i}", b["text"], b.get("source")
    for p in draft["projects"]:
        yield f"project:{p.get('source')}", f"{p.get('name', '')}. {p['text']}", p.get("source")


def audit(draft: dict, job: dict, m: dict, profile: Profile, taxonomy: Taxonomy) -> dict:
    findings: list[dict] = []
    ev = profile.evidence()
    summaries = profile.summary_sources()

    def add(level, code, where, message):
        findings.append({"level": level, "code": code, "where": where, "message": message})

    total_words = 0
    for where, text, source in _blocks(draft):
        total_words += word_count(text)
        for level, code, message in check_block(text, source, profile, taxonomy):
            add(level, code, where, message)
        if where == "headline":
            continue
        if source not in summaries:
            if word_count(text) > MAX_BULLET_WORDS:
                add("warning", "BULLET_LARGO", where, f"{word_count(text)} palabras; apunta a menos de {MAX_BULLET_WORDS}.")
            if any(normalize(text).startswith(w) for w in WEAK_STARTS):
                add("warning", "VERBO_DEBIL", where, "Empieza con una fórmula pasiva; usa un verbo de acción y el resultado.")
        elif word_count(text) > MAX_SUMMARY_WORDS:
            add("warning", "RESUMEN_LARGO", where, f"{word_count(text)} palabras; un reclutador lee 3–4 líneas.")

    for name in draft["skills"]:
        total_words += 1
        key = taxonomy.key_for(name, register=False)
        if not profile.is_backed(key):
            add("error", "SKILL_NO_RESPALDADA", "skills", f"'{name}' figura en Habilidades sin evidencia.")

    for e in draft["experience"]:
        if e["source"] not in ev:
            add("error", "SIN_FUENTE", e["source"], "Experiencia inexistente en el perfil.")

    cv_text = " ".join(t for _, t, _ in _blocks(draft)) + " " + ", ".join(draft["skills"])
    cv_keys = set(taxonomy.find_in(cv_text))
    total_w = sum(r["weight"] for r in m["rows"]) or 1.0
    covered_w = sum(r["weight"] for r in m["rows"] if r["status"] == "backed" and r["key"] in cv_keys)
    for r in m["rows"]:
        if r["status"] == "backed" and r["key"] not in cv_keys:
            add("warning", "KEYWORD_AUSENTE", "cv",
                f"'{r['name']}' ({r['importance']}) está respaldada pero no aparece en el CV.")
        elif r["status"] != "backed" and r["importance"] == "required":
            add("info", "RIESGO_ENTREVISTA", "cv",
                f"'{r['name']}' es requisito y no está respaldada: prepara una respuesta honesta.")

    personal = draft.get("personal") or {}
    for k in ("email", "phone", "linkedin"):
        if not personal.get(k):
            add("warning", "CONTACTO_INCOMPLETO", "personal", f"Falta `{k}`.")
    if total_words > MAX_TOTAL_WORDS:
        add("warning", "CV_EXTENSO", "cv", f"~{total_words} palabras; probablemente supera 2 páginas.")
    elif total_words < MIN_TOTAL_WORDS:
        add("warning", "CV_BREVE", "cv", f"~{total_words} palabras; puede parecer poco sustentado.")

    errors = sum(f["level"] == "error" for f in findings)
    clarity_issues = sum(f["code"] in ("BULLET_LARGO", "VERBO_DEBIL", "RESUMEN_LARGO", "CV_EXTENSO", "CV_BREVE")
                         for f in findings)
    return {
        "job_id": job["job_id"],
        "audited_at": now_iso(),
        "passed": errors == 0,
        "scores": {
            "integrity": max(0, 100 - 25 * errors),
            "keyword_coverage": round(100 * covered_w / total_w, 1),
            "clarity": max(0, 100 - 8 * clarity_issues),
        },
        "total_words": total_words,
        "findings": findings,
    }


def to_markdown(job: dict, a: dict) -> str:
    s = a["scores"]
    out = [f"# Auditoría de reclutador — {job['title']}", "",
           f"**Resultado:** {'APROBADO' if a['passed'] else 'BLOQUEADO (corrige los errores antes de enviar)'}", "",
           f"- Integridad (todo es defendible): {s['integrity']}/100",
           f"- Cobertura de keywords respaldadas: {s['keyword_coverage']}/100",
           f"- Claridad: {s['clarity']}/100",
           f"- Extensión: ~{a['total_words']} palabras", ""]
    for level, title in (("error", "Errores"), ("warning", "Advertencias"), ("info", "Notas")):
        items = [f for f in a["findings"] if f["level"] == level]
        if items:
            out += [f"## {title}", ""] + [f"- `{f['code']}` [{f['where']}] {f['message']}" for f in items] + [""]
    return "\n".join(out)
