"""Fuentes internacionales con API o feed PÚBLICO y documentado (Línea B).

Cada fuente devuelve ofertas normalizadas:
    {source, url, apply_url, title, company, text, regions (lista o None), salary {min,max,currency,period}, tags}

`regions` sale SOLO del campo oficial de "países/regiones desde donde se puede trabajar" de cada fuente
(no de la ubicación de la empresa). Si la fuente no lo trae, queda None y decide el clasificador de texto.

Uso responsable: 1 consulta diaria por fuente (caché en data/cache/), User-Agent identificado y atribución:
RemoteOK pide citar la fuente (columna `fuente` del listado y del registro).
"""
from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from ..utils import normalize

UA = "cv-titan/0.3 (busqueda personal de empleo de un candidato)"


def _get(url: str, timeout: int = 60, retries: int = 1) -> bytes:
    from .. import telemetry
    telemetry.visit(url)
    from ..net import fetch
    for attempt in range(retries + 1):
        try:
            return fetch(url, {"User-Agent": UA, "Accept": "application/json, application/rss+xml, */*"}, timeout)[0]
        except Exception:
            if attempt == retries:
                raise
            import time
            time.sleep(5)
    return b""


def _cached(cache_dir: Path, key: str, fetch) -> object:
    """Una descarga por fuente y día (respeta límites como 'no más de 1 vez por hora')."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{key}-{date.today():%Y%m%d}.json"
    if path.exists():
        from .. import telemetry
        telemetry.cache_read()
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _text(html_text: str | None) -> str:
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", html_text or "")
    t = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"[ \t]+", " ", t).strip()


def _salary_from_text(s: str | None) -> dict:
    """'$170k - $200k', '$80,000 - $100,000/year', '50-60 USD/hour' -> {min,max,currency,period}."""
    if not s:
        return {}
    t = s.lower().replace(",", "")
    nums = [float(n) * (1000 if k else 1) for n, k in re.findall(r"(\d+(?:\.\d+)?)\s*(k)?", t)]
    nums = [n for n in nums if n >= 10]
    if not nums:
        return {}
    cur = "EUR" if "€" in t or "eur" in t else "GBP" if "£" in t or "gbp" in t else "USD"
    period = "hora" if re.search(r"hour|/h\b|hr\b", t) else "mes" if re.search(r"month|/mo\b|mes", t) else (
        "año" if max(nums) >= 20000 else "mes")
    return {"salary_min": min(nums), "salary_max": max(nums), "salary_currency": cur, "salary_period": period}


# ---------------------------------------------------------------- fuentes
def remotive(cache: Path) -> list[dict]:
    out = []
    for cat in ("software-dev", "data", "devops", "customer-support", "all-others"):
        data = _cached(cache, f"remotive-{cat}", lambda c=cat: json.loads(
            _get(f"https://remotive.com/api/remote-jobs?category={c}")))
        for j in data.get("jobs", []):
            regions = [r.strip() for r in (j.get("candidate_required_location") or "").split(",") if r.strip()]
            out.append({"source": "Remotive", "url": j.get("url"), "apply_url": j.get("url"), "title": j.get("title"),
                        "company": j.get("company_name"), "text": _text(j.get("description")),
                        "regions": regions or None, "salary": _salary_from_text(j.get("salary")),
                        "tags": j.get("tags") or []})
    return out


def remoteok(cache: Path) -> list[dict]:
    data = _cached(cache, "remoteok", lambda: json.loads(_get("https://remoteok.com/api")))
    out = []
    for j in data[1:] if isinstance(data, list) else []:
        loc = (j.get("location") or "").strip()
        # RemoteOK mezcla "Worldwide"/"USA" (restricción) con ciudades (sede): solo se usa si es región.
        regions = [loc] if loc and re.search(r"(?i)worldwide|anywhere|global|latam|america|usa|united states|europe|"
                                             r"\beu\b|\buk\b|canada|emea|apac|asia", loc) else None
        sal = {}
        if j.get("salary_min"):
            sal = {"salary_min": float(j["salary_min"]), "salary_max": float(j.get("salary_max") or j["salary_min"]),
                   "salary_currency": "USD", "salary_period": "año"}
        out.append({"source": "Remote OK", "url": j.get("url"), "apply_url": j.get("apply_url") or j.get("url"),
                    "title": j.get("position"), "company": j.get("company"), "text": _text(j.get("description")),
                    "regions": regions, "salary": sal, "tags": j.get("tags") or []})
    return out


def himalayas(cache: Path, pages: int = 5) -> list[dict]:
    def fetch():
        jobs = []
        for p in range(pages):
            jobs += json.loads(_get(f"https://himalayas.app/jobs/api?limit=20&offset={p * 20}")).get("jobs", [])
        return {"jobs": jobs}
    out = []
    for j in _cached(cache, "himalayas", fetch).get("jobs", []):
        sal = {}
        if j.get("minSalary"):
            per = {"year": "año", "month": "mes", "hour": "hora"}.get(str(j.get("salaryPeriod") or "year").lower(), "año")
            sal = {"salary_min": float(j["minSalary"]), "salary_max": float(j.get("maxSalary") or j["minSalary"]),
                   "salary_currency": j.get("currency") or "USD", "salary_period": per}
        regions = j.get("locationRestrictions") or []
        out.append({"source": "Himalayas", "url": j.get("applicationLink"), "apply_url": j.get("applicationLink"),
                    "title": j.get("title"), "company": j.get("companyName"),
                    "text": _text(j.get("description") or j.get("excerpt")),
                    "regions": regions or ["Worldwide"] if j.get("locationRestrictions") == [] else (regions or None),
                    "salary": sal, "tags": j.get("categories") or []})
    return out


def jobicy(cache: Path) -> list[dict]:
    out = []
    for tag in ("python", "data", "devops", "ai", "support"):
        try:
            data = _cached(cache, f"jobicy-{tag}", lambda t=tag: json.loads(
                _get(f"https://jobicy.com/api/v2/remote-jobs?count=50&tag={t}")))
        except Exception:
            continue
        for j in data.get("jobs", []):
            geo = j.get("jobGeo") or ""
            regions = [g.strip() for g in geo.split(",") if g.strip()] or None
            sal = {}
            if j.get("annualSalaryMin"):
                sal = {"salary_min": float(j["annualSalaryMin"]),
                       "salary_max": float(j.get("annualSalaryMax") or j["annualSalaryMin"]),
                       "salary_currency": j.get("salaryCurrency") or "USD", "salary_period": "año"}
            out.append({"source": "Jobicy", "url": j.get("url"), "apply_url": j.get("url"), "title": j.get("jobTitle"),
                        "company": j.get("companyName"), "text": _text(j.get("jobDescription") or j.get("jobExcerpt")),
                        "regions": regions, "salary": sal, "tags": j.get("jobIndustry") or []})
    return out


def arbeitnow(cache: Path) -> list[dict]:
    data = _cached(cache, "arbeitnow", lambda: json.loads(_get("https://www.arbeitnow.com/api/job-board-api")))
    out = []
    for j in data.get("data", []):
        if not j.get("remote"):
            continue                       # Arbeitnow: solo los marcados remotos (el resto es presencial en Europa)
        out.append({"source": "Arbeitnow", "url": j.get("url"), "apply_url": j.get("url"), "title": j.get("title"),
                    "company": j.get("company_name"), "text": _text(j.get("description")), "regions": None,
                    "salary": {}, "tags": j.get("tags") or []})
    return out


def weworkremotely(cache: Path) -> list[dict]:
    out = []
    for cat in ("remote-full-stack-programming-jobs", "remote-back-end-programming-jobs", "remote-programming-jobs",
                "remote-devops-sysadmin-jobs", "remote-customer-support-jobs"):
        def fetch(c=cat):
            root = ET.fromstring(_get(f"https://weworkremotely.com/categories/{c}.rss"))
            items = []
            for it in root.iter("item"):
                items.append({k: (it.findtext(k) or "") for k in ("title", "link", "description", "region")})
            return items
        try:
            items = _cached(cache, f"wwr-{cat}", fetch)
        except Exception:
            continue                               # una categoría caída no anula las demás
        for it in items:
            company, _, title = (it["title"] or "").partition(":")
            region = (it.get("region") or "").strip()
            out.append({"source": "We Work Remotely", "url": it["link"], "apply_url": it["link"],
                        "title": title.strip() or it["title"], "company": company.strip(),
                        "text": _text(it.get("description")), "regions": [region] if region else None,
                        "salary": {}, "tags": []})
    return out


def _per_token(tokens: list[str], one) -> list[dict]:
    """Escanea cada portal de empresa en paralelo; un portal caído no detiene al resto."""
    from concurrent.futures import ThreadPoolExecutor

    def safe(tok):
        try:
            return one(tok)
        except Exception:
            return []
    with ThreadPoolExecutor(max_workers=16) as pool:
        return [job for jobs in pool.map(safe, list(dict.fromkeys(tokens or []))) for job in jobs]


def greenhouse(cache: Path, tokens: list[str]) -> list[dict]:
    return _per_token(tokens, lambda tok: _greenhouse_one(cache, tok))


def _greenhouse_one(cache: Path, tok: str) -> list[dict]:
    out = []
    data = _cached(cache, f"gh-{tok}", lambda t=tok: json.loads(
        _get(f"https://boards-api.greenhouse.io/v1/boards/{t}/jobs?content=true")))
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name") or ""
        out.append({"source": f"Greenhouse ({tok})", "url": j.get("absolute_url"), "apply_url": j.get("absolute_url"),
                    "title": j.get("title"), "company": j.get("company_name") or tok,
                    "text": _text(html.unescape(j.get("content") or "")),
                    "regions": [loc] if re.search(r"(?i)remote", loc) else None, "salary": {}, "tags": [],
                    # Portal ATS: sin «remote» en la ubicación oficial, la vacante es presencial en ese lugar.
                    "onsite": None if re.search(r"(?i)remote|anywhere", loc) else (loc or "location not stated")})
    return out


def lever(cache: Path, tokens: list[str]) -> list[dict]:
    return _per_token(tokens, lambda tok: _lever_one(cache, tok))


def _lever_one(cache: Path, tok: str) -> list[dict]:
    out = []
    data = _cached(cache, f"lever-{tok}", lambda t=tok: json.loads(
        _get(f"https://api.lever.co/v0/postings/{t}?mode=json")))
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        loc = cats.get("location") or ""
        regions = [loc] if (j.get("workplaceType") == "remote" or re.search(r"(?i)remote", loc)) else None
        out.append({"source": f"Lever ({tok})", "url": j.get("hostedUrl"), "apply_url": j.get("applyUrl"),
                    "title": j.get("text"), "company": tok, "text": _text(j.get("description")),
                    "regions": regions, "salary": {}, "tags": [],
                    "onsite": None if regions else (loc or "location not stated")})
    return out


def known_boards(cache: Path, db_path: Path | None = None) -> dict[str, list[str]]:
    """Escáner mundial: portales Greenhouse/Lever de empresas que TITAN ya encontró (por el resolutor de ATS o en
    el registro de vacantes). Crece solo con cada ejecución. Ashby se excluye (CAPTCHA en cada postulación)."""
    found: dict[str, set[str]] = {"greenhouse": set(), "lever": set()}
    for f in (cache / "ats").glob("*.json"):
        m = re.match(r"(greenhouse|lever)-(.+)-\d{8}\.json$", f.name)
        if m:
            try:
                if json.loads(f.read_text(encoding="utf-8")):
                    found[m.group(1)].add(m.group(2))
            except (OSError, ValueError):
                pass
    if db_path and db_path.exists():
        import sqlite3
        try:
            con = sqlite3.connect(str(db_path))
            urls = " ".join(r[0] or "" for r in con.execute("SELECT url FROM vacancy_sources"))
            con.close()
            found["greenhouse"] |= set(re.findall(r"greenhouse\.io/([a-z0-9_-]+)/jobs", urls))
            found["lever"] |= set(re.findall(r"jobs\.lever\.co/([a-z0-9_-]+)/", urls))
        except Exception:
            pass
    found["greenhouse"] -= {"embed", "v1"}
    return {k: sorted(v) for k, v in found.items()}


FETCHERS = {"remotive": remotive, "remoteok": remoteok, "himalayas": himalayas, "jobicy": jobicy,
            "arbeitnow": arbeitnow, "weworkremotely": weworkremotely}


# ---------------------------------------------------------------- elegibilidad por región oficial
OPEN_REGION = (r"worldwide|anywhere|global|work from anywhere|latam|latin america|south america|americas|"
               r"\bchile\b|north (and|&) south america|any (country|location)|international")


def region_eligibility(regions: list[str] | None) -> str | None:
    """Usa SOLO el campo oficial de regiones permitidas. None = la fuente no lo informa."""
    if not regions:
        return None
    joined = normalize(" | ".join(regions))
    if re.search(OPEN_REGION, joined):
        return f"ok: región permitida ({', '.join(regions)[:60]})"
    return f"excluido: solo {', '.join(regions)[:60]} (restricción publicada por el portal)"


# ---------------------------------------------------------------- resolver la vacante en el ATS del empleador
# Los agregadores (Remote OK, WWR, Remotive…) exigen cuenta propia para mostrar el enlace de postulación.
# Muchas empresas publican la MISMA vacante en un ATS con API pública y formulario sin cuenta:
# Greenhouse, Lever y Ashby. Se buscan por el nombre de la empresa y se cruza por cargo.
def _slugs(company: str) -> list[str]:
    n = re.sub(r"\b(inc|llc|ltd|gmbh|corp|co|sa|s\.a\.|ab|bv|technologies|technology|labs|hq)\b\.?", " ",
               normalize(company or ""))
    words = [w for w in re.findall(r"[a-z0-9]+", n) if w]
    if not words:
        return []
    out = ["".join(words), "-".join(words), words[0]]
    return list(dict.fromkeys(s for s in out if len(s) >= 3))


def _title_key(t: str) -> set[str]:
    stop = {"the", "a", "an", "of", "and", "for", "remote", "latam", "worldwide", "senior", "sr", "ii", "iii",
            "full", "time", "contract", "en", "de", "la"}
    return {w for w in re.findall(r"[a-z0-9+#]+", normalize(t)) if w not in stop}


def _similar(a: str, b: str) -> float:
    x, y = _title_key(a), _title_key(b)
    return len(x & y) / max(1, len(x | y))


def _ats_jobs(cache: Path, ats: str, slug: str) -> list[dict]:
    urls = {"greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
            "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json",
            "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}"}

    def fetch():
        try:
            data = json.loads(_get(urls[ats], timeout=20, retries=0))
        except Exception:
            return []
        if ats == "greenhouse":
            return [{"title": j.get("title"), "url": j.get("absolute_url"),
                     "location": (j.get("location") or {}).get("name")} for j in data.get("jobs", [])]
        if ats == "lever":
            return [{"title": j.get("text"), "url": j.get("applyUrl") or j.get("hostedUrl"),
                     "location": (j.get("categories") or {}).get("location")} for j in data if isinstance(j, dict)]
        return [{"title": j.get("title"), "url": j.get("applyUrl") or j.get("jobUrl"), "location": j.get("location")}
                for j in data.get("jobs", [])]
    return _cached(cache / "ats", f"{ats}-{slug}", fetch)


def resolve_employer_job(cache: Path, company: str, title: str, min_similarity: float = 0.6) -> dict | None:
    """{'ats','url','title','location'} de la misma vacante en el ATS público del empleador, o None."""
    best, best_s = None, 0.0
    for slug in _slugs(company):
        for ats in ("greenhouse", "lever", "ashby"):
            for j in _ats_jobs(cache, ats, slug):
                s = _similar(title, j.get("title") or "")
                if s > best_s and j.get("url"):
                    best, best_s = {**j, "ats": ats, "similarity": round(s, 2)}, s
        if best_s >= 0.99:
            break
    return best if best and best_s >= min_similarity else None
