"""Búsqueda de vacantes -> listado CSV para que el candidato elija.

    cvtitan buscar "python" "power bi" --en getonboard,linkedin --lugar Chile
    (abre data/busqueda.csv en Excel, marca con x la columna «postular», guarda)
    cvtitan postular --lista data/busqueda.csv

Dónde busca (fuentes por palabra clave, config/search_keywords.yaml):
  - getonboard    https://www.getonbrd.com/jobs-<frase>                 público
  - computrabajo  https://cl.computrabajo.com/trabajo-de-<frase>        público
  - chiletrabajos https://www.chiletrabajos.cl/trabajos/<frase>         público
  - indeed        https://cl.indeed.com/jobs?q=<frase>&l=Chile          navegador (puede pedir verificación)
  - linkedin      búsqueda Easy Apply en Chile                          navegador con tu sesión
Y portales oficiales de empresas (config/companies.yaml): todas sus vacantes publicadas.
"""
from __future__ import annotations

import csv
import html
import re
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

from .. import evidence, job_intel
from ..market import MarketCache, job_record
from .legal import remote_eligibility
from ..db import PROCESS_STATUSES
from ..utils import Workspace, slugify
from .batch import BatchApplier, clean_job_url, is_job_url, linkedin_search_url
from .platforms import detect

COLUMNS = ["postular", "score", "score_bruto", "skills_detectadas", "area", "obligatorios_%", "cargo", "empresa",
           "pais", "ciudad", "modalidad", "nivel", "contrato", "jornada", "elegibilidad", "salario", "vs_pretension", "brechas", "plataforma", "url"]
# Áreas de Get on Board (segmento de la URL) que corresponden a tecnología y datos.
TECH_AREAS = {"programming", "programacion", "data-science-analytics", "machine-learning-ai", "sysadmin-devops-qa",
              "desarrollo-mobile", "mobile-development", "cybersecurity", "ciberseguridad", "design-ux"}
MIN_SKILLS = 6          # con menos skills detectadas, el % de cobertura no es confiable


def area_of(url: str) -> str:
    m = re.search(r"getonbrd\.com/jobs/([^/]+)/", url)
    return m.group(1) if m else ""


def adjusted_score(score: float, n_skills: int, area: str) -> float:
    """El score de cobertura sube artificialmente si la vacante menciona pocas skills técnicas
    (p. ej. «Excel y Power BI» en un cargo comercial). Se pondera por cantidad de skills y área."""
    factor = min(1.0, n_skills / MIN_SKILLS)
    if area and area not in TECH_AREAS:
        factor *= 0.6
    return round(score * factor, 1)


def vs_expectation(salary: dict, prefs: dict) -> str:
    gross = prefs.get("salary_gross") or {}
    cur = (salary or {}).get("salary_currency")
    top = (salary or {}).get("salary_max") or (salary or {}).get("salary_min")
    if not cur and top and float(top) >= 100_000:
        cur = "CLP"                                  # montos de 6+ dígitos sin moneda: pesos chilenos
    if not cur or not top or cur not in gross:
        return ""
    diff = (float(top) - float(gross[cur])) / float(gross[cur]) * 100
    return "ok" if diff >= 0 else f"bajo ({diff:.0f}%)"
YES = {"x", "si", "sí", "s", "1", "yes", "y", "true"}


KEYWORDS_PATH = Path(__file__).resolve().parents[2] / "config" / "search_keywords.yaml"
SOURCES = ("getonboard", "computrabajo", "chiletrabajos", "indeed", "linkedin")
COMPANIES_PATH = KEYWORDS_PATH.parent / "companies.yaml"
SF_PAGE = 25            # resultados por página en portales SuccessFactors
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


def source_url(source: str, keyword: str, location: str = "Chile") -> str:
    slug = slugify(keyword, 60)
    if source == "getonboard":
        return f"https://www.getonbrd.com/jobs-{slug}"            # buscador de texto de Get on Board
    if source == "computrabajo":
        return f"https://cl.computrabajo.com/trabajo-de-{slug}"
    if source == "chiletrabajos":
        return f"https://www.chiletrabajos.cl/trabajos/{slug}"
    if source == "indeed":
        return f"https://cl.indeed.com/jobs?q={quote_plus(keyword)}&l={quote_plus(location)}"
    if source == "linkedin":
        return linkedin_search_url(keyword, location)
    raise ValueError(f"Fuente desconocida: {source}. Disponibles: {', '.join(SOURCES)}")


def load_companies(path: Path = COMPANIES_PATH) -> list[dict]:
    from ..utils import load_yaml
    return list(load_yaml(path).get("companies") or []) if path.exists() else []


def company_sources(companies: list[dict]) -> list[tuple[str, str]]:
    """[(url de listado, empresa)] de los portales con ATS soportado (todas las páginas configuradas)."""
    out = []
    for c in companies:
        if c.get("ats") != "successfactors":
            continue
        base = c["url"].rstrip("/")
        loc = quote_plus(str(c.get("location") or ""))
        for page in range(int(c.get("max_pages", 2))):
            out.append((f"{base}/search/?q=&locationsearch={loc}&startrow={page * SF_PAGE}", c["name"]))
    return out


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def load_keywords(path: Path = KEYWORDS_PATH, groups: list[str] | None = None) -> list[tuple[str, str, list[str]]]:
    """[(grupo, palabra, fuentes)] desde config/search_keywords.yaml."""
    from ..utils import load_yaml
    data = load_yaml(path)
    cfg = dict(data.get("groups") or {})
    dic = data.get("dictionary") or {}
    if dic.get("enabled", True) and dic:
        from ..job_dictionary import search_groups
        cfg.update(search_groups(dic.get("priorities") or ["P1", "P2"], dic.get("sources")))
    if groups and "diccionario" in groups:           # «diccionario» = todos los grupos dic_*
        groups = [g for g in groups if g != "diccionario"] + [g for g in cfg if g.startswith("dic_")]
    unknown = set(groups or []) - set(cfg)
    if unknown:
        raise ValueError(f"Grupos inexistentes: {', '.join(sorted(unknown))}. Disponibles: {', '.join(cfg)}")
    out = []
    for name, g in cfg.items():
        if groups and name not in groups:
            continue
        for kw in g.get("keywords") or []:
            out.append((name, str(kw), list(g.get("sources") or SOURCES)))
    return out


def search_sources(keywords: list[str], where: list[str], location: str,
                   groups: list[str] | None = None, path: Path = KEYWORDS_PATH) -> list[str]:
    """Palabras sueltas -> se buscan en `where`. Sin palabras -> diccionario (fuentes del grupo ∩ `where`)."""
    pairs = ([(None, kw, list(where)) for kw in keywords] if keywords
             else load_keywords(path, groups))
    urls: list[str] = []
    for _, kw, sources in pairs:
        for src in sources:
            if src in where:
                u = source_url(src, kw, location)
                if u not in urls:
                    urls.append(u)
    return urls


PAGE_CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "pages"
PAGE_CACHE_HOURS = 24


def http_get(url: str, cache: bool | None = None) -> str:
    """GET con caché en disco para AVISOS (no para listados, que cambian). `cache=False` la omite."""
    import hashlib
    import time as _time
    use_cache = is_job_url(url) if cache is None else cache
    path = PAGE_CACHE / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".html")
    if use_cache and path.exists() and _time.time() - path.stat().st_mtime < PAGE_CACHE_HOURS * 3600:
        return path.read_text(encoding="utf-8", errors="replace")
    from ..net import fetch
    raw, charset = fetch(url, {"User-Agent": UA, "Accept-Language": "es-CL,es;q=0.9"}, 20)
    body = raw.decode(charset or "utf-8", errors="replace")
    if use_cache:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        except OSError:
            pass
    return body


STOPWORDS = {"de", "del", "la", "el", "en", "y", "para", "con", "los", "las", "of", "and", "the", "in", "for"}


def keyword_of(search_url: str) -> str | None:
    """Palabra clave de una URL de búsqueda construida por source_url (None si no es una búsqueda)."""
    from urllib.parse import parse_qs, unquote
    u = urlparse(search_url)
    q = parse_qs(u.query)
    if "linkedin.com" in u.netloc:
        return (q.get("keywords") or [None])[0]
    if "indeed.com" in u.netloc:
        return (q.get("q") or [None])[0]
    for pattern in (r"^/jobs-(.+)$", r"^/trabajos/(.+)$", r"^/trabajo-de-(.+)$"):
        m = re.match(pattern, u.path)
        if m:
            return unquote(m.group(1)).replace("-", " ")
    return None


def _stems(keyword: str) -> list[str]:
    from ..utils import normalize
    words = [w for w in re.findall(r"[a-z0-9#+.]+", normalize(keyword)) if w not in STOPWORDS and len(w) > 1]
    return [w[:5] if len(w) > 5 else w for w in words]           # "mineria"/"minera"/"minero" -> "miner"


def is_relevant(text: str, keywords: set[str]) -> bool:
    """¿El aviso menciona al menos una de las búsquedas que lo trajeron? (todas sus palabras, por raíz).
    Descarta los avisos «destacados» que los portales muestran cuando no hay coincidencias."""
    from ..utils import normalize
    if not keywords:
        return True
    norm = normalize(text)
    return any(all(stem in norm for stem in _stems(kw)) for kw in keywords if _stems(kw))


HTTP_HOSTS = {"www.getonbrd.com", "getonbrd.com", "cl.computrabajo.com", "www.chiletrabajos.cl", "chiletrabajos.cl"}


class Searcher(BatchApplier):
    """Reutiliza el navegador del robot para recorrer listados y leer vacantes que piden login."""

    def __init__(self, *a, companies: list[dict] | None = None, **kw):
        super().__init__(*a, **kw)
        self.company_by_host = {host_of(c["url"]): c["name"] for c in companies or []
                                if c.get("ats") == "successfactors"}
        self.no_limit: set[str] = set()
        self.found_by: dict[str, set[str]] = {}    # url -> palabras clave que la trajeron
        self.workers = 24                           # descargas HTTP simultáneas (listados y avisos públicos)

    def is_http(self, url: str) -> bool:
        """Sitios públicos que se leen sin navegador (más rápido y sin consumir la sesión)."""
        return host_of(url) in HTTP_HOSTS or host_of(url) in self.company_by_host

    def expand(self, url: str, limit: int) -> list[str]:
        from .. import telemetry
        telemetry.visit(url)
        if self.is_http(url) and not is_job_url(url):
            try:
                page = http_get(url)
            except Exception as e:
                self.say(f"  could not open {url}: {type(e).__name__}")
                return []
            links: list[str] = []
            for href in re.findall(r'href="([^"]+)"', page):
                u = clean_job_url(urljoin(url, html.unescape(href)))
                if is_job_url(u) and u not in links:
                    links.append(u)
            return links[:limit]
        return super().expand(url, limit)

    def read_job(self, url: str) -> dict:
        from .. import telemetry
        telemetry.visit(url)
        from .linkedin_guard import is_linkedin
        if is_linkedin(url):
            ok, why = self.linkedin.allow("read")
            if not ok:
                raise RuntimeError(f"LinkedIn: {why}")
        if self.is_http(url):
            raw = job_intel.parse_html(http_get(url))       # públicas: sin navegador, más rápido
            if raw.get("title"):                            # Computrabajo: "Trabajos de <cargo> - <ciudad>"
                raw["title"] = re.sub(r"^Trabajos? de\s+", "", raw["title"]).strip()
            company = self.company_by_host.get(host_of(url))
            if company:                                     # SuccessFactors: "<cargo> | <ubicación>"
                raw["title"] = (raw.get("title") or "").split(" | ")[0].strip()
                raw["company"] = raw.get("company") or company
            return raw
        page = self.runner.context().new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            self.runner.settle(page, 3000)
            raw = job_intel.parse_html(page.content())
            for sel in (".jobs-description__content", "#job-details", ".description__text", "main"):
                if len(raw["text"]) >= 400:
                    break
                try:
                    if page.locator(sel).count():
                        raw["text"] = page.locator(sel).first.inner_text(timeout=3000)
                except Exception:
                    pass
            if len(raw["text"]) < 400:
                raw["text"] = page.inner_text("body")
            title = raw.get("title") or page.title()
            parts = [x.strip() for x in title.split(" | ")]
            if len(parts) >= 3 and parts[-1].lower() == "linkedin":      # "Cargo | Empresa | LinkedIn"
                raw["title"], raw["company"] = parts[0], raw.get("company") or parts[1]
            else:
                raw["title"] = title
            return raw
        finally:
            page.close()

    def scan(self, sources: list[str], limit: int) -> list[dict]:
        from playwright.sync_api import sync_playwright

        tax, profile = self.engine.load()
        rows: list[dict] = []
        with sync_playwright() as pw:
            self.runner.pw = pw
            try:
                urls: list[str] = []
                skip_hosts: set[str] = set()
                from concurrent.futures import ThreadPoolExecutor
                http_srcs = [x for x in dict.fromkeys(sources) if self.is_http(x) and not is_job_url(x)]
                prefetched: dict[str, list[str]] = {}
                if http_srcs:
                    lim_of = (lambda x: 10_000 if x in self.no_limit else limit)
                    with ThreadPoolExecutor(max_workers=self.workers) as pool:
                        for src_, found_ in zip(http_srcs, pool.map(lambda x: self.expand(x, lim_of(x)), http_srcs)):
                            prefetched[src_] = found_
                    self.say(f"  {len(http_srcs)} public-board searches run in parallel")
                for src in sources:
                    host = host_of(src)
                    if host in skip_hosts:
                        continue
                    lim = 10_000 if src in self.no_limit else limit
                    found = None
                    if src in prefetched:
                        found = [u for u in prefetched[src] if u != src or detect(src).key == "generic"]
                    else:
                        self.say(f"Searching {src}")
                    for attempt in ((1, 2) if found is None else ()):             # si cerraste la ventana, se reabre una vez
                        try:
                            found = [u for u in self.expand(src, lim) if u != src or detect(src).key == "generic"]
                            break
                        except Exception as e:
                            self.runner.ctx = None
                            if attempt == 2:
                                self.say(f"  search failed here ({type(e).__name__}); moving to the next source")
                    if found is None:
                        continue
                    if not found and not self.is_http(src) and detect(src).requires_login:
                        skip_hosts.add(host)          # sin sesión: no insistir con cada palabra clave
                        self.say(f"  Skipping the rest of {detect(src).name}: sign in with `cvtitan sesiones`.")
                    if src not in prefetched:
                        self.say(f"  {len(found)} job(s)")
                    kw = keyword_of(src)
                    for u in found:
                        if u not in urls:
                            urls.append(u)
                        if kw:
                            self.found_by.setdefault(u, set()).add(kw)
                        else:
                            self.found_by[u] = set()      # vino de un portal de empresa o URL directa: no filtrar
                known = 0
                pending: list[str] = []
                for url in urls:
                    prev = self.db.find_by_url(url)
                    v = self.registry.by_url(url)
                    if (prev and prev["status"] in PROCESS_STATUSES) or \
                            (v and v["status"] in ("SUBMITTED_CONFIRMED", "SUBMISSION_UNKNOWN", "CLOSED")):
                        known += 1                    # ya enviada o ya descartada: no se vuelve a leer
                        continue
                    pending.append(url)
                urls = pending
                self.say(f"\n{len(urls)} new job(s) to analyze"
                         + (f" ({known} already reviewed, skipped)" if known else "") + "...")
                http_urls = [u for u in urls if self.is_http(u)]
                pre_raw: dict[str, object] = {}
                if http_urls:
                    def _fetch(u):
                        try:
                            return u, self.read_job(u)
                        except Exception as e:      # se informa abajo, en orden
                            return u, e
                    with ThreadPoolExecutor(max_workers=self.workers) as pool:
                        pre_raw = dict(pool.map(_fetch, http_urls))
                skipped_irrelevant = 0
                market_cache = MarketCache(self.engine.ws.root / "data" / "market_cache.jsonl")
                for i, url in enumerate(urls, 1):
                    try:
                        raw = pre_raw[url] if url in pre_raw else self.read_job(url)
                        if isinstance(raw, Exception):
                            raise raw
                        job = job_intel.analyze(raw["text"], tax, title=raw.get("title"), company=raw.get("company"),
                                                url=url, job_id="busqueda", meta=raw)
                        m = evidence.match(job, profile, tax)
                        if not is_relevant(f"{raw.get('title') or ''} {raw['text']}", self.found_by.get(url, set())):
                            skipped_irrelevant += 1
                            continue
                        market_cache.put(job_record(url, raw, job, m, detect(url).name))
                    except Exception as e:  # una vacante rara no detiene la búsqueda
                        if "Closed" in type(e).__name__:
                            self.runner.ctx = None        # ventana cerrada: la próxima lectura la reabre
                        self.say(f"  [{i}] could not read {url}: {type(e).__name__}")
                        continue
                    gaps = [r["name"] for r in m["rows"] if r["status"] != "backed" and r["importance"] == "required"]
                    area = area_of(url)
                    n = len(m["rows"])
                    rows.append({
                        "postular": "", "score": adjusted_score(m["score"], n, area), "score_bruto": m["score"],
                        "skills_detectadas": n, "area": area,
                        "vs_pretension": vs_expectation(job.get("salary") or {}, profile.data.get("preferences") or {}),
                        "obligatorios_%": m["required_coverage"],
                        "cargo": job.get("title") or "", "empresa": job.get("company") or "",
                        "pais": job.get("country") or "", "ciudad": job.get("city") or "", "modalidad": job.get("modality") or "",
                        "nivel": job.get("seniority") or "",
                        "salario": job_intel.format_salary(job.get("salary") or {}),
                        "brechas": ", ".join(gaps[:6]), "plataforma": detect(url).name, "url": url,
                        "contrato": job_intel.detect_contract(job.get("title") or "", raw["text"]),
                        "jornada": job_intel.detect_workload(job.get("title") or "", raw["text"]),
                        "elegibilidad": remote_eligibility(raw["text"], job.get("country"), job.get("modality")),
                    })
                    self.say(f"  [{i}] {rows[-1]['score']:>5} · {job.get('title')} — {job.get('company') or '?'}")
                if skipped_irrelevant:
                    self.say(f"\n{skipped_irrelevant} posting(s) discarded: they do not mention your search terms "
                             "(destacados del portal).")
            finally:
                if self.runner.ctx:
                    try:
                        self.runner.ctx.close()
                    except Exception:
                        pass
        rows.sort(key=lambda r: -float(r["score"] or 0))
        unique, seen = [], set()                     # el mismo aviso publicado con dos URLs
        for r in rows:
            key = (r["cargo"].strip().lower(), r["empresa"].strip().lower())
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique


def write_list(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig y ";" para que Excel en español lo abra con columnas y acentos correctos.
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter=";")
        w.writeheader()
        w.writerows(rows)
    return path


def read_selected(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    delimiter = ";" if text.count(";") >= text.count(",") else ","
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    return [r["url"].strip() for r in reader
            if (r.get("postular") or "").strip().lower() in YES and (r.get("url") or "").startswith("http")]


def run_search(ws: Workspace, keywords: list[str], where: list[str], location: str, urls: list[str],
               limit: int, out: Path, headless: bool = False, groups: list[str] | None = None,
               companies: bool = True, say=print) -> tuple[Path, list[dict]]:
    path = ws.root / "config" / "search_keywords.yaml"
    sources = search_sources(keywords, where, location, groups, path if path.exists() else KEYWORDS_PATH) + list(urls)
    cpath = ws.root / "config" / "companies.yaml"
    company_list = load_companies(cpath if cpath.exists() else COMPANIES_PATH) if companies else []
    company_urls = [u for u, _ in company_sources(company_list)]
    searcher = Searcher(ws, headless=headless, companies=company_list, say=say)
    searcher.no_limit = set(company_urls)          # los portales de empresa se recorren completos
    rows = searcher.scan(sources + company_urls, limit)
    manual = [c for c in company_list if c.get("ats") in ("manual", "pendiente")]
    if manual:
        say("\nPortals to review manually (no automatic connector yet):")
        for c in manual:
            say(f"  - {c['name']}: {c['url']}" + (f"  ({c['note']})" if c.get("note") else ""))
    return write_list(rows, out), rows
