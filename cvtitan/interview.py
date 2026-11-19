"""Preparación de entrevista: preguntas probables ancladas en evidencia y en brechas."""
from __future__ import annotations

from .profile import Profile
from .utils import PACKAGE_ROOT, load_yaml, normalize

RESOURCES_PATH = PACKAGE_ROOT / "config" / "study_resources.yaml"


def study_plan(job: dict, m: dict, path=RESOURCES_PATH) -> list[dict]:
    """Elige recursos de estudio (enlaces) según el cargo, las skills pedidas y las brechas."""
    if not path.exists():
        return []
    cfg = load_yaml(path)
    sources, resources = cfg.get("sources", {}), cfg.get("resources", {})
    title = normalize(job.get("title"))
    asked = {r["key"] for r in m["rows"]}
    gaps = {r["key"] for r in m["rows"] if r["status"] != "backed" and r["importance"] in ("required", "responsibilities")}
    senior = job.get("seniority") in ("semi-senior", "senior", "lead")
    seen: set[str] = set()
    plan = []
    for rule in cfg.get("rules", []):
        hit = (rule.get("always")
               or any(normalize(w) in title for w in rule.get("title", []))
               or bool(asked & set(rule.get("skills", [])))
               or bool(gaps & set(rule.get("gaps", [])))
               or (rule.get("salary_or_senior") and (bool(job.get("salary")) or senior)))
        if not hit:
            continue
        items = []
        for rid in rule["resources"]:
            r = resources.get(rid)
            if not r or rid in seen:
                continue
            seen.add(rid)
            src = sources[r["source"]]
            url = src["url"] + (r.get("path") or (f"#{r['anchor']}" if r.get("anchor") else ""))
            items.append({"title": r["title"], "url": url, "source": src["name"]})
        if items:
            plan.append({"reason": rule["reason"], "items": items})
    return plan


def build(job: dict, m: dict, profile: Profile) -> str:
    company = job.get("company") or "la empresa"
    out = [f"# Preparación de entrevista — {job['title']} ({company})", "",
           "Cada respuesta debe salir de tu evidencia real. Usa el formato STAR: "
           "Situación, Tarea, Acción y Resultado.", "",
           "## Preguntas de apertura", "",
           f"1. Cuéntame sobre ti y por qué te interesa este cargo en {company}.",
           "2. ¿Qué experiencia tuya se parece más a lo que haríamos en este rol?",
           "3. ¿Cuál es el logro profesional del que te sientes más orgulloso/a y por qué?", ""]

    backed = [r for r in m["rows"] if r["status"] == "backed"]
    backed.sort(key=lambda r: -r["weight"])
    if backed:
        out += ["## Habilidades respaldadas: preguntas técnicas y de comportamiento", ""]
        for r in backed[:8]:
            out.append(f"### {r['name']} ({r['importance']})")
            out.append(f"- **Pregunta probable:** Dame un ejemplo concreto en que usaste {r['name']}. "
                       "¿Qué problema resolviste y cuál fue el resultado?")
            out.append(f"- **Profundización:** ¿Qué harías distinto hoy? ¿Qué limitaciones encontraste con {r['name']}?")
            for e in r["evidence"][:2]:
                out.append(f"- **Tu evidencia (`{e['id']}`):** {e['text']}")
            out.append("")

    risks = [r for r in m["rows"] if r["status"] != "backed" and r["importance"] in ("required", "responsibilities")]
    if risks:
        out += ["## Brechas: cómo responder con honestidad", ""]
        for r in risks:
            out.append(f"### {r['name']}")
            out.append(f"- **Pregunta probable:** ¿Qué experiencia tienes con {r['name']}?")
            if r["status"] == "implicit":
                ids = ", ".join(e["id"] for e in r["evidence"])
                out.append(f"- **Enfoque:** hay evidencia implícita en {ids}. Revisa si puedes defenderla con un caso real.")
            else:
                out.append("- **Enfoque:** reconoce el nivel real, conecta con una habilidad adyacente que sí "
                           "dominas y muestra un plan concreto (curso, proyecto, plazo). No exageres.")
            if r.get("note"):
                out.append(f"- **Tu nota en el perfil:** {r['note']}")
            out.append("")

    out += ["## Preguntas para hacerle al entrevistador", "",
            "1. ¿Cómo se mide el éxito en este rol durante los primeros 90 días?",
            "2. ¿Cuál es el mayor desafío técnico o de negocio que enfrenta el equipo hoy?",
            "3. ¿Cómo está compuesto el equipo y con qué áreas interactúa el cargo?", ""]
    plan = study_plan(job, m)
    if plan:
        out += ["## Plan de estudio para esta vacante", "",
                "Material abierto, elegido según el cargo y tus brechas (en inglés):", ""]
        for block in plan:
            out.append(f"**{block['reason']}**")
            out += [f"- [{i['title']}]({i['url']}) — {i['source']}" for i in block["items"]]
            out.append("")
    if job.get("years_required") and not m["years"]["ok"]:
        out += ["## Nota sobre experiencia", "",
                f"La vacante pide {job['years_required']} años y tu perfil suma {m['years']['candidate']}. "
                "Prepara ejemplos de alcance e impacto que compensen la diferencia.", ""]
    return "\n".join(out)
