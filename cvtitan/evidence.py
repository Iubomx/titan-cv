"""02 — Candidate Evidence Agent: matriz de compatibilidad vacante vs. evidencia verificable."""
from __future__ import annotations

from .profile import Profile
from .taxonomy import Taxonomy
from .utils import now_iso

STATUS_LABEL = {
    "backed": "Respaldada",
    "implicit": "Evidencia implícita (validar)",
    "to_demonstrate": "Por demostrar",
    "gap": "Brecha",
}


def match(job: dict, profile: Profile, taxonomy: Taxonomy) -> dict:
    ev = profile.evidence()
    rows = []
    for s in job["skills"]:
        key = s["key"]
        declared = profile.skill_map.get(key)
        evidence = []
        if profile.is_backed(key):
            status = "backed"
            evidence = [{"id": i, "text": ev[i]["text"]} for i in declared.get("evidence", []) if i in ev]
        elif declared:
            status = "to_demonstrate"
        else:
            implicit = [i for i in ev if key in profile.evidence_skill_keys(i)]
            status = "implicit" if implicit else "gap"
            evidence = [{"id": i, "text": ev[i]["text"]} for i in implicit]
        rows.append({
            "key": key,
            "name": s["name"],
            "importance": s["importance"],
            "weight": s["weight"],
            "status": status,
            "evidence": evidence,
            "note": declared.get("note") if declared else None,
        })

    total = sum(r["weight"] for r in rows) or 1.0
    backed_w = sum(r["weight"] for r in rows if r["status"] == "backed")
    potential_w = sum(r["weight"] for r in rows if r["status"] in ("backed", "implicit"))
    required = [r for r in rows if r["importance"] == "required"]
    req_cov = (sum(1 for r in required if r["status"] == "backed") / len(required)) if required else None

    years = profile.years_experience()
    years_req = job.get("years_required")
    score = round(100 * backed_w / total, 1)
    if years_req and years < years_req:
        score = round(score * max(0.7, years / years_req), 1)

    return {
        "job_id": job["job_id"],
        "matched_at": now_iso(),
        "score": score,
        "potential_score": round(100 * potential_w / total, 1),
        "required_coverage": round(100 * req_cov, 1) if req_cov is not None else None,
        "years": {"required": years_req, "candidate": years,
                  "ok": None if not years_req else years >= years_req},
        "recommendation": _recommend(score, req_cov),
        "approved": False,
        "rows": rows,
    }


def _recommend(score: float, req_cov: float | None) -> str:
    if score >= 70 and (req_cov is None or req_cov >= 0.7):
        return "Postular: ajuste alto. Adaptar CV y priorizar."
    if score >= 50:
        return "Postular con CV adaptado y preparar respuestas para las brechas."
    if score >= 30:
        return "Ajuste parcial: postular solo si hay interés estratégico."
    return "Ajuste bajo: no priorizar, salvo que la vacante sea clave."


def to_markdown(job: dict, m: dict) -> str:
    out = [
        f"# Matriz de compatibilidad — {job['title']}" + (f" ({job['company']})" if job.get("company") else ""),
        "",
        f"- **Score de evidencia:** {m['score']}/100",
        f"- **Score potencial** (si validas evidencia implícita): {m['potential_score']}/100",
    ]
    if m["required_coverage"] is not None:
        out.append(f"- **Cobertura de requisitos obligatorios:** {m['required_coverage']}%")
    y = m["years"]
    if y["required"]:
        out.append(f"- **Experiencia:** pide {y['required']} años, tienes {y['candidate']} "
                   f"({'cumple' if y['ok'] else 'no cumple'})")
    out += [f"- **Recomendación:** {m['recommendation']}",
            f"- **Aprobado para generar CV:** {'sí' if m['approved'] else 'no'}", "",
            "| Skill | Importancia | Estado | Evidencia |", "|---|---|---|---|"]
    for r in m["rows"]:
        ev = "; ".join(f"`{e['id']}`" for e in r["evidence"][:3]) or (r.get("note") or "—")
        out.append(f"| {r['name']} | {r['importance']} | {STATUS_LABEL[r['status']]} | {ev} |")

    implicit = [r for r in m["rows"] if r["status"] == "implicit"]
    if implicit:
        out += ["", "## Evidencia implícita por validar", "",
                "Estas skills aparecen en tu experiencia pero no están declaradas en `candidate/profile.yaml`. "
                "Si son verdaderas y defendibles, agrégalas como `backed` con su evidencia:", ""]
        out += [f"- **{r['name']}** -> " + ", ".join(e["id"] for e in r["evidence"]) for r in implicit]
    gaps = [r for r in m["rows"] if r["status"] in ("gap", "to_demonstrate") and r["importance"] == "required"]
    if gaps:
        out += ["", "## Brechas en requisitos obligatorios", ""]
        out += [f"- **{r['name']}** ({STATUS_LABEL[r['status']]}): no se incluirá en el CV. "
                "Prepárala como tema de entrevista o plan de aprendizaje." for r in gaps]
    return "\n".join(out) + "\n"
