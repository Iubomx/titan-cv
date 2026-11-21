"""Análisis de mercado a partir de vacantes públicas (no de perfiles de personas).

    cvtitan mercado                 -> usa data/busqueda.csv (la última búsqueda)
    cvtitan mercado --lista X.csv

Responde, para TU perfil:
  1. Qué skills piden más las vacantes que encontraste (y si las tienes respaldadas).
  2. Qué skills aparecen en las vacantes mejor pagadas.
  3. Qué brechas, si las cerraras, subirían más tu compatibilidad promedio.
  4. Qué palabras exactas (respaldadas) conviene usar en el CV y en LinkedIn para aparecer en búsquedas.

Cada vacante analizada se guarda en data/market_cache.jsonl (solo datos del aviso, no del candidato).
"""
from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import evidence, job_intel, local_sources, markets
from . import fx as fx_mod
from .profile import Profile
from .taxonomy import Taxonomy
from .utils import Workspace, now_iso, write_text

from .fx import DEFAULT_FX  # noqa: F401  (se reexporta: line_b y las pruebas lo importan desde aquí)


def job_record(url: str, raw: dict, job: dict, m: dict, source: str = "") -> dict:
    s = job.get("salary") or {}
    return {
        "url": url, "title": job.get("title"), "company": job.get("company"), "source": source,
        "country": job.get("country"), "modality": job.get("modality"), "seniority": job.get("seniority"),
        "language": job.get("language"),
        "salary": {k: s.get(k) for k in ("salary_min", "salary_max", "salary_currency", "salary_period")},
        "skills": [{"key": r["key"], "name": r["name"], "importance": r["importance"], "weight": r["weight"]}
                   for r in m["rows"]],
        "years_required": job.get("years_required"),
        "analyzed_at": now_iso(),
    }


class MarketCache:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                    self.data[rec["url"]] = rec
                except (ValueError, KeyError):
                    continue

    def put(self, rec: dict) -> None:
        self.data[rec["url"]] = rec
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _monthly_usd(salary: dict, fx: dict) -> float | None:
    cur = salary.get("salary_currency")
    lo, hi = salary.get("salary_min"), salary.get("salary_max")
    value = ((lo or 0) + (hi or 0)) / (2 if lo and hi else 1) if (lo or hi) else None
    if not value:
        return None
    if not cur and value >= markets.active().no_currency_threshold:
        cur = markets.active().default_currency
    if cur not in fx:
        return None
    period = salary.get("salary_period") or "mes"
    factor = {"mes": 1, "año": 1 / 12, "hora": 160}.get(period, 1)
    return value * fx[cur] * factor


def collect(urls: list[str], cache: MarketCache, tax: Taxonomy, profile: Profile, say=print) -> list[dict]:
    """Registros de mercado para `urls`: del caché o leyendo en paralelo los avisos públicos."""
    from .apply.search import host_of, http_get, load_companies

    company_by_host = {host_of(c["url"]): c["name"] for c in load_companies() if c.get("ats") == "successfactors"}
    company_hosts = set(company_by_host)
    missing = [u for u in urls if u not in cache.data and (host_of(u) in local_sources.http_hosts() or host_of(u) in company_hosts)]
    if missing:
        say(f"Leyendo {len(missing)} aviso(s) que faltan en el caché (en paralelo)...")

        def fetch(url):
            try:
                return url, job_intel.parse_html(http_get(url))
            except Exception:
                return url, None

        with ThreadPoolExecutor(max_workers=8) as pool:
            for url, raw in pool.map(fetch, missing):
                if not raw or len(raw.get("text") or "") < 200:
                    continue
                if host_of(url) in company_by_host:        # SuccessFactors: "<cargo> | <ubicación>"
                    raw["title"] = (raw.get("title") or "").split(" | ")[0].strip()
                    raw["company"] = raw.get("company") or company_by_host[host_of(url)]
                job = job_intel.analyze(raw["text"], tax, title=raw.get("title"), company=raw.get("company"),
                                        url=url, job_id="mercado", meta=raw)
                cache.put(job_record(url, raw, job, evidence.match(job, profile, tax)))
    return [cache.data[u] for u in urls if u in cache.data]


def analyze_market(records: list[dict], profile: Profile, fx: dict | None = None) -> dict:
    fx = fx or DEFAULT_FX
    n = len(records)
    demand: dict[str, dict] = {}
    gain: defaultdict[str, float] = defaultdict(float)
    pay = defaultdict(list)
    all_pay = []
    for rec in records:
        rows = rec["skills"]
        total = sum(r["weight"] for r in rows) or 1.0
        usd = _monthly_usd(rec.get("salary") or {}, fx)
        if usd:
            all_pay.append(usd)
        for r in rows:
            d = demand.setdefault(r["key"], {"key": r["key"], "name": r["name"], "jobs": 0, "required": 0})
            d["jobs"] += 1
            d["required"] += r["importance"] in ("required", "responsibilities")
            if not profile.is_backed(r["key"]):
                gain[r["key"]] += 100 * r["weight"] / total        # puntos que sumaría en esa vacante
            if usd:
                pay[r["key"]].append(usd)
    for k, d in demand.items():
        d["pct"] = round(100 * d["jobs"] / n, 1) if n else 0
        d["backed"] = profile.is_backed(k)
        d["avg_gain"] = round(gain[k] / n, 2) if n else 0
        prices = pay.get(k) or []
        d["paid_jobs"] = len(prices)
        d["median_usd"] = round(statistics.median(prices)) if prices else None
    median_all = round(statistics.median(all_pay)) if all_pay else None
    ranked = sorted(demand.values(), key=lambda d: (-d["jobs"], -d["required"]))
    return {
        "n": n, "with_salary": len(all_pay), "median_usd": median_all,
        "demand": ranked,
        "gaps": sorted([d for d in demand.values() if not d["backed"]], key=lambda d: -d["avg_gain"]),
        "premium": sorted([d for d in demand.values() if d["paid_jobs"] >= 3 and d["median_usd"]],
                          key=lambda d: -d["median_usd"]),
        "keywords": [d for d in ranked if d["backed"]],
    }


def to_markdown(res: dict, fx: dict) -> str:
    out = [f"# Análisis de mercado — {res['n']} vacantes", "",
           "Basado en avisos públicos de tu última búsqueda (no en perfiles de personas).", ""]
    if not res["n"]:
        return "\n".join(out + ["No hay vacantes analizadas. Ejecuta `cvtitan buscar` primero."])

    out += ["## 1. Lo que más piden", "", "| Skill | % de vacantes | Obligatoria en | ¿La tienes respaldada? |",
            "|---|---|---|---|"]
    for d in res["demand"][:20]:
        out.append(f"| {d['name']} | {d['pct']}% | {d['required']} | {'yes' if d['backed'] else 'no'} |")

    out += ["", "## 2. Brechas que más suben tu compatibilidad", "",
            "Puntos que ganaría tu compatibilidad promedio si respaldaras esa skill (con un proyecto o logro real).",
            "", "| Skill | Ganancia promedio | Vacantes que la piden | Obligatoria en |", "|---|---|---|---|"]
    for d in res["gaps"][:12]:
        out.append(f"| {d['name']} | +{d['avg_gain']} pts | {d['jobs']} ({d['pct']}%) | {d['required']} |")

    out += ["", "## 3. Skills de las vacantes mejor pagadas", ""]
    if res["premium"]:
        out += [f"Mediana general: **USD {res['median_usd']:,}/mes** en {res['with_salary']} avisos con sueldo "
                "publicado. Montos convertidos a USD con tipos de cambio supuestos (editables en "
                "`config/settings.yaml` -> `fx`).".replace(",", "."), "",
                "| Skill | Mediana USD/mes | Avisos con sueldo | ¿La tienes? |", "|---|---|---|---|"]
        for d in res["premium"][:15]:
            out.append(f"| {d['name']} | {d['median_usd']:,} | {d['paid_jobs']} | {'yes' if d['backed'] else 'no'} |"
                       .replace(",", "."))
    else:
        out.append("Muy pocos avisos publican sueldo para comparar (se necesitan al menos 3 por skill).")

    out += ["", "## 4. Palabras clave para tu CV y LinkedIn", "",
            "Skills **respaldadas** ordenadas por demanda. Úsalas con este nombre exacto en el titular, el resumen "
            "y la sección de aptitudes: así te encuentran los filtros automáticos y los reclutadores.", ""]
    out.append(", ".join(f"**{d['name']}**" for d in res["keywords"][:15]) or "—")
    out += ["", "## Cómo leer esto", "",
            "- Prioriza cerrar las brechas de la sección 2 que además estén en la sección 3.",
            "- Una brecha solo se cierra con evidencia real (proyecto, certificación o logro) y luego la marcas "
            "como `backed` en tu perfil. Nunca se agrega al CV sin respaldo.", ""]
    return "\n".join(out)


def run(ws: Workspace, csv_path: Path, say=print) -> tuple[Path, dict]:
    from .utils import load_yaml

    tax = Taxonomy.load(ws.taxonomy_path)
    profile = Profile.load(ws.profile_path, tax)
    settings = load_yaml(ws.settings_path) if ws.settings_path.exists() else {}
    fx = fx_mod.resolve(ws.root, settings)
    text = csv_path.read_text(encoding="utf-8-sig")
    urls = [r["url"] for r in csv.DictReader(text.splitlines(), delimiter=";") if (r.get("url") or "").startswith("http")]
    cache = MarketCache(ws.root / "data" / "market_cache.jsonl")
    records = collect(urls, cache, tax, profile, say)
    res = analyze_market(records, profile, fx)
    out = ws.root / "data" / "mercado.md"
    write_text(out, to_markdown(res, fx))
    return out, res
