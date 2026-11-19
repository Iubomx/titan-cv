"""01 — Job Intelligence Agent: convierte una vacante (URL o texto) en requisitos estructurados."""
from __future__ import annotations

import html
import json
import re
import urllib.request
from datetime import date

from .taxonomy import Taxonomy
from .utils import normalize, now_iso, slugify

# Orden importa: "requisitos deseables" debe clasificarse como preferred.
SECTION_MARKERS = [
    ("benefits", ["beneficios", "benefits", "ofrecemos", "we offer", "what we offer", "te ofrecemos"]),
    ("preferred", ["deseable", "deseables", "nice to have", "preferred", "bonus", "valoramos",
                   "sera un plus", "es un plus", "se valorara", "idealmente", "plus"]),
    ("required", ["requisitos", "requerimientos", "requirements", "required", "must have",
                  "qualifications", "lo que buscamos", "buscamos", "excluyente", "que necesitas",
                  "what you bring", "you have", "perfil", "conocimientos", "skills"]),
    ("responsibilities", ["responsabilidades", "funciones", "responsibilities", "what you'll do",
                          "what you will do", "que haras", "desafios", "tus tareas", "el rol",
                          "about the role", "descripcion del cargo"]),
]
INLINE_PREFERRED = ["deseable", "nice to have", "un plus", "valorable", "se valorara", "preferible",
                    "bonus", "idealmente", "ideally"]
INLINE_REQUIRED = ["excluyente", "obligatorio", "indispensable", "required", "must"]

WEIGHTS = {"required": 3.0, "responsibilities": 2.0, "general": 1.5, "preferred": 1.0}

SENIORITY = [
    ("lead", ["lead", "lider", "principal", "head of", "jefe", "jefa", "manager", "gerente"]),
    ("semi-senior", ["semi senior", "semi-senior", "ssr", "semisenior"]),   # antes que "senior"
    ("senior", ["senior", "sr.", "sr "]),
    ("junior", ["junior", "jr.", "jr "]),
    ("trainee", ["trainee", "practica", "practicante", "intern", "pasantia"]),
]
LANG_LEVELS = ["nativo", "native", "bilingue", "fluido", "fluent", "avanzado", "advanced",
               "intermedio", "intermediate", "basico", "basic", "c2", "c1", "b2", "b1", "a2"]


# ---------------------------------------------------------------------- captura
def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<li[^>]*>", "\n- ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|ul|ol|tr|section)>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(raw)
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _jsonld_jobposting(raw: str) -> dict | None:
    for block in re.findall(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', raw):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for item in data if isinstance(data, list) else data.get("@graph", [data]):
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def _first(value):
    return value[0] if isinstance(value, list) and value else value


def _posting_location(posting: dict) -> dict:
    loc = _first(posting.get("jobLocation")) or {}
    addr = (loc.get("address") if isinstance(loc, dict) else None) or {}
    if isinstance(addr, str):
        return {"city": addr, "country": None}
    country = addr.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name")
    out = {"city": addr.get("addressLocality"), "country": country}
    if posting.get("jobLocationType") == "TELECOMMUTE":
        out["modality"] = "remoto"
    return out


def _posting_salary(posting: dict) -> dict:
    sal = posting.get("baseSalary") or posting.get("estimatedSalary")
    sal = _first(sal)
    if not isinstance(sal, dict):
        return {}
    value = sal.get("value") or {}
    if not isinstance(value, dict):
        value = {"value": value}
    lo = value.get("minValue") or value.get("value")
    hi = value.get("maxValue") or value.get("value")
    period = {"HOUR": "hora", "MONTH": "mes", "YEAR": "año"}.get(str(value.get("unitText", "")).upper())
    try:
        lo, hi = (float(lo) if lo else None), (float(hi) if hi else None)
    except (TypeError, ValueError):
        return {}
    return {"salary_min": lo, "salary_max": hi, "salary_currency": sal.get("currency"), "salary_period": period}


COUNTRY_CODES = {"CL": "Chile", "PE": "Perú", "AR": "Argentina", "CO": "Colombia", "MX": "México",
                 "UY": "Uruguay", "ES": "España", "US": "Estados Unidos", "BR": "Brasil", "EC": "Ecuador",
                 "CA": "Canadá", "AU": "Australia"}


def _itemprop(raw: str, prop: str) -> str | None:
    m = (re.search(rf'(?is)<meta[^>]*content="([^"]*)"[^>]*itemprop="{prop}"', raw)
         or re.search(rf'(?is)itemprop="{prop}"[^>]*>([^<]*)<', raw))
    return html.unescape(m.group(1)).strip() if m and m.group(1).strip() else None


def _microdata_posting(raw: str) -> dict | None:
    """Vacantes con microdatos schema.org (p. ej. Get on Board): solo el cuerpo del aviso,
    sin las vacantes relacionadas ni la navegación, que contaminan skills y seniority."""
    start = re.search(r'(?i)itemprop="description"', raw)
    title = _itemprop(raw, "title")
    if not start or not title:
        return None
    end = re.search(r'(?i)itemprop="skills"', raw[start.end():])
    body = raw[start.end(): start.end() + end.start()] if end else raw[start.end(): start.end() + 60000]
    body = body[body.find(">") + 1:]
    company = None
    og = re.search(r'(?is)<meta[^>]*content="([^"]*)"[^>]*property="og:title"', raw)
    if og:                                   # "<cargo> at|en <empresa> - <lugar>"
        og_text = html.unescape(og.group(1)).strip()
        rest = og_text[len(title):] if og_text.startswith(title) else og_text
        m = re.match(r"\s*(?:at|en|in|@)\s+(.+?)(?:\s+-\s+[^-]*)?$", rest)
        company = m.group(1).strip() if m else None
    meta = {"text": _html_to_text(body), "title": title, "company": company}
    code = (_itemprop(raw, "addressCountry") or "").upper()
    if COUNTRY_CODES.get(code):
        meta["country"] = COUNTRY_CODES[code]
    if _itemprop(raw, "addressLocality"):
        meta["city"] = _itemprop(raw, "addressLocality")
    page_title = re.search(r"(?is)<title>(.*?)</title>", raw)
    if page_title and re.search(r"(?i)remote|work from home|remoto", page_title.group(1)):
        meta["modality"] = "remoto"
    if _itemprop(raw, "qualifications"):
        meta["seniority"] = _itemprop(raw, "qualifications")
    head = _html_to_text(raw[:start.start()])  # cabecera del aviso: "Gross salary $2200 - 3400 USD/month"
    sal = re.search(r"\$\s?([\d.,]+)\s*-\s*\$?\s?([\d.,]+)\s*USD\s*/\s*(month|mes)", head, re.I)
    if sal:
        to_num = lambda v: float(re.sub(r"[.,]", "", v))  # noqa: E731
        meta.update(salary_min=to_num(sal.group(1)), salary_max=to_num(sal.group(2)),
                    salary_currency="USD", salary_period="mes")
    skills = re.search(r'(?is)itemprop="skills"(.*?)</div>', raw)
    if skills:
        tags = [html.unescape(t).strip() for t in re.findall(r">([^<]+)</a>", skills.group(1))]
        if tags:
            meta["text"] += "\n\nTecnologías: " + ", ".join(tags) + "."
    return meta


LANG_WORDS = {
    "es": ["de", "la", "el", "y", "en", "para", "con", "los", "las", "del", "experiencia", "requisitos", "trabajo"],
    "en": ["the", "and", "to", "of", "for", "with", "you", "your", "we", "experience", "requirements", "will"],
    "pt": ["de", "e", "para", "com", "voce", "experiencia", "vaga", "nao", "uma", "requisitos"],
    "de": ["und", "der", "die", "das", "mit", "fur", "wir", "sie", "erfahrung", "kenntnisse"],
}


CONTRACT_TEMP = re.compile(
    r"(?<![a-z])(por proyecto|proyecto de \d+ meses|plazo fijo|contrato a plazo|freelance|honorarios|reemplazo|"
    r"temporal|temporada|part.?time|medio tiempo|contrato por obra|por obra o faena|fixed.?term|contractor|"
    r"temporary|short.?term)(?![a-z])")


PART_TIME = re.compile(
    r"(?<![a-z])(part.?time|medio tiempo|media jornada|jornada parcial|por horas|horario flexible|"
    r"(?:[1-3]?\d)\s*(?:hrs?|horas)\s*(?:semanales|a la semana|por semana|/\s*semana|al mes|mensuales)|"
    r"(?:[1-3]?\d)\s*(?:hours|hrs)\s*(?:per|a|/)\s*week|freelance)(?![a-z])")


def detect_workload(title: str, text: str) -> str:
    """'parcial' si el aviso indica pocas horas (part-time, medio tiempo, N horas/semana, freelance)."""
    head = normalize(f"{title or ''} {(text or '')[:4000]}")
    m = PART_TIME.search(head)
    return f"parcial ({m.group(1)})" if m else ""


def detect_contract(title: str, text: str) -> str:
    """'temporal' si el aviso es por proyecto, plazo fijo, freelance, reemplazo, etc.; '' si no lo indica."""
    head = normalize(f"{title or ''} {(text or '')[:4000]}")
    m = CONTRACT_TEMP.search(head)
    return f"temporal ({m.group(1)})" if m else ""


def detect_language(text: str) -> str:
    """Idioma predominante del aviso (es/en/pt/de) por frecuencia de palabras comunes."""
    words = re.findall(r"[a-z]+", normalize(text)[:20000])
    if not words:
        return "es"
    counts = {lang: sum(words.count(w) for w in vocab) for lang, vocab in LANG_WORDS.items()}
    return max(counts, key=counts.get)


# Texto de la plataforma (no del aviso) que el detector confundiría con requisitos.
BOILERPLATE = re.compile(r"(?i)sap as service provider|(powered by\s+)?sap\s+successfactors|successfactors|workday,? inc\.?|taleo")


def _strip_boilerplate(meta: dict) -> dict:
    if meta.get("text"):
        meta["text"] = BOILERPLATE.sub(" ", meta["text"])
    return meta


def parse_html(raw: str) -> dict:
    return _strip_boilerplate(_parse_html(raw))


def _parse_html(raw: str) -> dict:
    """HTML de una vacante -> texto + metadatos (JSON-LD JobPosting si existe)."""
    posting = _jsonld_jobposting(raw)
    if posting:
        org = posting.get("hiringOrganization") or {}
        meta = {
            "text": _html_to_text(posting.get("description", "")),
            "title": posting.get("title"),
            "company": org.get("name") if isinstance(org, dict) else None,
        }
        meta.update({k: v for k, v in _posting_location(posting).items() if v})
        meta.update({k: v for k, v in _posting_salary(posting).items() if v})
        return meta
    micro = _microdata_posting(raw)
    if micro:
        return micro
    title = re.search(r"(?is)<title>(.*?)</title>", raw)
    return {
        "text": _html_to_text(raw),
        "title": html.unescape(title.group(1)).strip() if title else None,
        "company": None,
    }


def fetch_url(url: str, timeout: int = 20) -> dict:
    """Descarga una vacante pública. Para LinkedIn/Indeed usa el navegador (automation)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; cv-titan/0.1)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
    return parse_html(raw)


COUNTRIES = {
    "Chile": ["chile", "santiago", "antofagasta", "valparaiso", "concepcion", "calama", "la serena", "iquique",
              "copiapo", "rancagua", "temuco", "puerto montt", "vina del mar"],
    "Perú": ["peru", "lima", "arequipa"],
    "Argentina": ["argentina", "buenos aires", "cordoba", "rosario", "mendoza"],
    "Colombia": ["colombia", "bogota", "medellin", "cali", "barranquilla"],
    "México": ["mexico", "cdmx", "monterrey", "guadalajara"],
    "Uruguay": ["uruguay", "montevideo"],
    "España": ["espana", "spain", "madrid", "barcelona", "valencia"],
    "Estados Unidos": ["united states", "estados unidos", "usa", "new york", "san francisco"],
    "Brasil": ["brasil", "brazil", "sao paulo", "rio de janeiro"],
    "Ecuador": ["ecuador", "quito", "guayaquil"],
    "Canadá": ["canada", "toronto", "vancouver"],
    "Australia": ["australia", "perth", "sydney", "brisbane"],
}
CURRENCIES = [("CLP", r"clp|pesos chilenos|\$\s?\d{1,3}(?:\.\d{3}){2,}"), ("USD", r"usd|us\$|dolares|dollars"),
              ("EUR", r"eur|€|euros"), ("UF", r"\buf\b")]


def _country(text_norm: str) -> str | None:
    best, best_pos = None, None
    for country, keys in COUNTRIES.items():
        for k in keys:
            m = re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", text_norm)
            if m and (best_pos is None or m.start() < best_pos):
                best, best_pos = country, m.start()
    return best


def _salary(text: str) -> dict:
    """Busca una línea con salario/renta/sueldo y un monto."""
    for line in text.splitlines():
        ln = normalize(line)
        if not re.search(r"salario|sueldo|renta|remuneracion|salary|compensation|rango salarial", ln):
            continue
        if not re.search(r"\d", ln):
            continue
        out = {"salary_text": line.strip()[:160]}
        for code, pat in CURRENCIES:
            if re.search(pat, ln):
                out["salary_currency"] = code
                break
        amounts = []
        for num, mult in re.findall(r"(\d+(?:[.,]\d+)*)\s*(k|mm|m|millones|mil)?\b", ln):
            if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", num):      # 1.500.000 / 2,500
                digits = re.sub(r"[.,]", "", num)
            else:                                                 # 1,5 / 2.5
                digits = num.replace(",", ".")
            try:
                value = float(digits)
            except ValueError:
                continue
            value *= {"k": 1e3, "mil": 1e3, "m": 1e6, "mm": 1e6, "millones": 1e6}.get(mult or "", 1)
            if value >= 100:
                amounts.append(value)
        if amounts:
            out["salary_min"], out["salary_max"] = min(amounts), max(amounts)
        if re.search(r"mensual|al mes|/mes|per month|monthly", ln):
            out["salary_period"] = "mes"
        elif re.search(r"anual|al ano|per year|annual|yearly", ln):
            out["salary_period"] = "año"
        return out
    return {}


# ---------------------------------------------------------------------- análisis
def _heading_section(line_norm: str) -> str | None:
    """Un encabezado es corto, no es viñeta, no termina en punto y empieza con un marcador
    (o termina en ':'). Así 'Dominio de Python (excluyente).' no se confunde con un título."""
    raw = line_norm.strip()
    if not raw or raw[0] in "-*•·" or raw.endswith((".", ";", ",")):
        return None
    stripped = raw.strip(" :#").strip()
    if not stripped or len(stripped.split()) > 7:
        return None
    for section, markers in SECTION_MARKERS:
        for m in markers:
            starts = re.match(rf"(?:\W*\w+\W+){{0,2}}{re.escape(m)}(?![a-z])", stripped)
            if starts or (raw.endswith(":") and m in stripped):
                return section
    return None


def _inline_override(line_norm: str) -> str | None:
    if any(m in line_norm for m in INLINE_PREFERRED):
        return "preferred"
    if any(re.search(rf"(?<![a-z]){re.escape(m)}(?![a-z])", line_norm) for m in INLINE_REQUIRED):
        return "required"
    return None


def _seniority(title: str, text: str) -> str | None:
    """El título manda. En el cuerpo se ignora 'lead': 'reportar al Líder Técnico' no hace lead el cargo."""
    for source, levels in ((normalize(title) + " ", SENIORITY), (normalize(text) + " ", SENIORITY[1:])):
        for level, markers in levels:
            if any(re.search(rf"(?<![a-z]){re.escape(m.strip())}(?![a-z])", source) for m in markers):
                return level
    return None


def _split_sentences(lines: list[str]) -> list[str]:
    """Portales como Get on Board entregan secciones en un solo párrafo; se separan por oración para que
    un 'idealmente' o 'deseable' afecte solo a su frase y no a todos los requisitos."""
    out = []
    for line in lines:
        if len(line) > 160 and not _heading_section(normalize(line)):
            out += [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-ZÁÉÍÓÚÑ¿])", line) if s.strip()]
        else:
            out.append(line)
    return out


def _years_required(text_norm: str) -> int | None:
    found = []
    for m in re.finditer(r"(\d{1,2})\s*\+?\s*(?:o mas\s+)?(?:anos|years|yrs|ano|year)", text_norm):
        window = text_norm[max(0, m.start() - 60): m.end() + 60]
        if "experien" in window:
            found.append(int(m.group(1)))
    return max(found) if found else None


def _languages(text_norm: str) -> list[dict]:
    out = []
    for name, markers in (("Inglés", ["ingles", "english"]), ("Portugués", ["portugues", "portuguese"])):
        for m in markers:
            idx = text_norm.find(m)
            if idx >= 0:
                window = text_norm[max(0, idx - 40): idx + 60]
                level = next((lv for lv in LANG_LEVELS if re.search(rf"\b{lv}\b", window)), None)
                out.append({"name": name, "level": level})
                break
    return out


def _modality(text_norm: str) -> str | None:
    if re.search(r"hibrid|hybrid", text_norm):
        return "híbrido"
    if re.search(r"remot|remote|teletrabajo|home office", text_norm):
        return "remoto"
    if re.search(r"presencial|on-site|onsite", text_norm):
        return "presencial"
    return None


def analyze(text: str, taxonomy: Taxonomy, title: str | None = None, company: str | None = None,
            url: str | None = None, job_id: str | None = None, meta: dict | None = None) -> dict:
    lines = _split_sentences([ln.strip() for ln in text.splitlines() if ln.strip()])
    if not title and lines:
        title = lines[0][:120]
    title = title or "Vacante"

    section = "general"
    skills: dict[str, dict] = {}
    responsibilities: list[str] = []
    requirements: list[str] = []
    for line in lines:
        ln = normalize(line)
        found = taxonomy.find_in(line)
        heading = None if found else _heading_section(ln)
        if heading:
            section = heading
            continue
        if section == "benefits":
            continue
        category = _inline_override(ln) or section
        if category == "responsibilities":
            responsibilities.append(line.lstrip("-*• ").strip())
        elif category in ("required", "preferred"):
            requirements.append(line.lstrip("-*• ").strip())
        for key, count in found.items():
            entry = skills.setdefault(key, {"key": key, "name": taxonomy.name(key),
                                            "importance": category, "mentions": 0, "context": line[:160]})
            entry["mentions"] += count
            if WEIGHTS[category] > WEIGHTS[entry["importance"]]:
                entry["importance"] = category
                entry["context"] = line[:160]

    for e in skills.values():
        e["weight"] = round(WEIGHTS[e["importance"]] + min(1.0, 0.25 * (e["mentions"] - 1)), 2)
    ordered = sorted(skills.values(), key=lambda e: (-e["weight"], e["name"].lower()))

    text_norm = normalize(text)
    job_id = job_id or f"{date.today():%Y%m%d}-{slugify(' '.join(filter(None, [company, title])), 50)}"
    meta = meta or {}
    salary = {k: meta[k] for k in ("salary_min", "salary_max", "salary_currency", "salary_period") if meta.get(k)}
    salary = salary or _salary(text)
    return {
        "job_id": job_id,
        "title": title,
        "company": company,
        "url": url,
        "analyzed_at": now_iso(),
        "country": meta.get("country") or _country(text_norm),
        "city": meta.get("city"),
        "seniority": _seniority(meta.get("seniority") or title, text),
        "years_required": _years_required(text_norm),
        "modality": meta.get("modality") or _modality(text_norm),
        "salary": salary,
        "languages": _languages(text_norm),
        "language": detect_language(text),
        "skills": ordered,
        "requirements": requirements,
        "responsibilities": responsibilities,
        "enriched_by": "heuristics",
    }


def enrich(job: dict, facts, taxonomy: Taxonomy) -> dict:
    """Mezcla los datos extraídos por el LLM (llm.JobFacts) en el análisis heurístico."""
    for field in ("country", "city", "modality", "seniority", "years_required"):
        value = getattr(facts, field)
        if value:
            job[field] = value
    if facts.company and not job.get("company"):
        job["company"] = facts.company
    if facts.title and (not job.get("title") or len(job["title"]) > 90):
        job["title"] = facts.title
    if facts.salary_text or facts.salary_min:
        job["salary"] = {k: v for k, v in {
            "salary_text": facts.salary_text, "salary_min": facts.salary_min, "salary_max": facts.salary_max,
            "salary_currency": facts.salary_currency, "salary_period": facts.salary_period}.items() if v}

    skills = {s["key"]: s for s in job["skills"]}
    for importance, names in (("required", facts.required_skills), ("preferred", facts.preferred_skills)):
        for name in names:
            key = taxonomy.key_for(name)
            entry = skills.get(key)
            if entry is None:
                skills[key] = {"key": key, "name": taxonomy.name(key), "importance": importance,
                               "mentions": 1, "context": "detectado por IA", "weight": WEIGHTS[importance]}
            elif importance == "required" and entry["importance"] != "required":
                entry["importance"] = "required"
                entry["weight"] = round(WEIGHTS["required"] + min(1.0, 0.25 * (entry["mentions"] - 1)), 2)
    job["skills"] = sorted(skills.values(), key=lambda e: (-e["weight"], e["name"].lower()))
    if facts.responsibilities and not job.get("responsibilities"):
        job["responsibilities"] = facts.responsibilities
    if facts.languages:
        job["languages_text"] = facts.languages
    job["enriched_by"] = "llm"
    return job


def format_salary(s: dict | None) -> str:
    if not s:
        return ""
    lo, hi = s.get("salary_min"), s.get("salary_max")
    if lo or hi:
        rng = f"{lo:,.0f}" if lo == hi or not hi else (f"{lo:,.0f} – {hi:,.0f}" if lo else f"{hi:,.0f}")
        rng = rng.replace(",", ".")
        return " ".join(filter(None, [s.get("salary_currency"), rng, f"/ {s['salary_period']}" if s.get("salary_period") else ""]))
    return s.get("salary_text", "")


def to_markdown(job: dict) -> str:
    out = [f"# {job['title']}" + (f" — {job['company']}" if job.get("company") else ""), ""]
    for label, key in (("País", "country"), ("Ciudad", "city"), ("Seniority", "seniority"),
                       ("Años de experiencia", "years_required"), ("Modalidad", "modality"), ("URL", "url")):
        if job.get(key):
            out.append(f"- **{label}:** {job[key]}")
    if job.get("salary"):
        out.append(f"- **Salario:** {format_salary(job['salary'])}")
    if job.get("languages"):
        out.append("- **Idiomas:** " + ", ".join(
            f"{l['name']} ({l['level'] or 'nivel no indicado'})" for l in job["languages"]))
    out += ["", "## Skills detectadas", "", "| Skill | Importancia | Peso | Menciones |", "|---|---|---|---|"]
    out += [f"| {s['name']} | {s['importance']} | {s['weight']} | {s['mentions']} |" for s in job["skills"]]
    if job.get("requirements"):
        out += ["", "## Requisitos", ""] + [f"- {r}" for r in job["requirements"]]
    if job.get("responsibilities"):
        out += ["", "## Responsabilidades", ""] + [f"- {r}" for r in job["responsibilities"]]
    return "\n".join(out) + "\n"
