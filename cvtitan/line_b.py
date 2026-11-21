"""Línea B — empleo remoto internacional desde Chile.

    cvtitan auto --linea B --simular

Pasos: fuentes públicas (+ LinkedIn remoto si hay sesión) -> filtro de cargo -> duplicados (entre portales y con el
historial) -> elegibilidad (región oficial del portal o texto) -> análisis vs perfil -> sueldo normalizado a USD/mes
-> puntaje de línea -> decisión. Registro en data/auto/B/. No envía si `send_enabled: false` en config/lines.yaml.
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import datetime
from urllib.parse import quote_plus

from . import evidence, job_intel, markets, scoring, sources, telemetry
from .apply import intl_sources
from .apply.legal import remote_eligibility
from .registry import norm_company, norm_title
from .apply.search import adjusted_score
from .db import DB, PROCESS_STATUSES
from . import fx as fx_mod
from .market import _monthly_usd
from .profile import Profile
from .taxonomy import Taxonomy
from .utils import PACKAGE_ROOT, Workspace, load_yaml, normalize

def ELIG_EN(counts) -> dict:
    names = {"ok": "eligible", "ambiguo": "ambiguous", "excluido": "excluded"}
    return {names.get(k, k): v for k, v in dict(counts).items()}


# Títulos que fijan el país o la región del cargo («-US», «(UK)», «Canada», «EMEA»…): no es remoto desde Chile.
TITLE_PLACE = re.compile(r"(?<![A-Za-z])(US|USA|U\.S\.|UK|EMEA|APAC|EU|DACH|ANZ)(?![A-Za-z])|"
                         r"(?i:\b(united states|canada|united kingdom|europe|germany|france|india|australia|"
                         r"new zealand|brazil|japan|singapore)\b)")


LINES_PATH = PACKAGE_ROOT / "config" / "lines.yaml"
COLUMNS = ["decision", "nivel", "motivo", "score_linea", "compatibilidad", "pts_elegibilidad", "pts_sueldo", "pts_experiencia", "elegibilidad", "sueldo_usd_mes", "cargo", "empresa",
           "fuente", "regiones", "idioma", "nivel", "brechas", "url"]


def load_line(ws: Workspace, key: str) -> dict:
    path = ws.root / "config" / "lines.yaml"
    cfg = load_yaml(path if path.exists() else LINES_PATH).get("lines") or {}
    if key not in cfg:
        raise ValueError(f"Línea inexistente: {key}. Disponibles: {', '.join(cfg)}")
    return cfg[key]


def fingerprint(company: str | None, title: str | None) -> str:
    """Huella de una oferta para detectar duplicados entre portales y contra el historial.

    Usa la misma normalización que el registro global (`registry.norm_company` / `norm_title`): sin sufijos de
    empresa (Inc, S.A., Group...), sin «(Remote)», «[LATAM]» ni « - Ciudad», y con «Sr.»/«Jr.» como senior/junior."""
    return f"{norm_company(company)}|{norm_title(title)}"


def _flat(text: str) -> str:
    """Normaliza para comparar títulos: sin tildes, minúsculas y guiones/barras como espacios («Full-Stack»)."""
    return re.sub(r"[-_/]+", " ", normalize(text))


def title_matches(title: str, tags: list, line: dict) -> bool:
    t = _flat(f"{title} {' '.join(map(str, tags or []))}")
    excl = re.sub(r"\s*\|\s*", "|", (line.get("exclude_titles") or "").strip())
    if excl and re.search(excl, normalize(title)):
        return False
    # (?:e?s)? : acepta el plural («Data Engineers»).
    if any(re.search(rf"(?<![a-z]){re.escape(_flat(k))}(?:e?s)?(?![a-z])", t) for k in line.get("keywords") or []):
        return True
    if line.get("dictionary_priorities"):
        from .job_dictionary import title_regex
        return bool(re.search(title_regex(line["dictionary_priorities"]), normalize(title))
                    or re.search(title_regex(line["dictionary_priorities"]), _flat(title)))
    return False


def linkedin_urls(line: dict) -> list[str]:
    li = line.get("linkedin") or {}
    if not li.get("enabled"):
        return []
    base = "https://www.linkedin.com/jobs/search/?keywords={k}&location={l}&f_WT=2"
    urls = [base.format(k=quote_plus(k), l=quote_plus(loc)) for k in li.get("keywords") or [] for loc in
            li.get("locations") or []]
    cities = li.get("us_cities") or {}
    if cities.get("enabled"):
        urls += [base.format(k=quote_plus(k), l=quote_plus(c)) for k in cities.get("keywords") or []
                 for c in cities.get("cities") or []]
    return urls


def score_line(m: dict, n_skills: int, elig: str, usd: float | None, years_ok: bool | None, years: tuple,
               line: dict) -> tuple[float, dict]:
    w = line.get("scoring") or {}
    sal = line.get("salary") or {}
    compat = adjusted_score(m["score"], n_skills, "")
    sc = scoring.active()
    elig_pts = sc.eligibility_ok_points if elig.startswith("ok") else sc.eligibility_ambiguous_points
    if usd is None:
        sal_pts = sc.salary_unknown_points
    elif usd >= float(sal.get("target_monthly", 5000)):
        sal_pts = sc.salary_target_points
    elif usd >= float(sal.get("min_monthly", 3000)):
        sal_pts = sc.salary_min_points
    else:
        sal_pts = sc.salary_below_points
    req, cand = years
    exp_pts = 100 if years_ok in (None, True) else max(0, min(100, 100 * cand / req)) if req else 100
    parts = {"compatibility": compat, "eligibility": elig_pts, "salary": sal_pts, "experience": exp_pts}
    total = sum(parts[k] * float(w.get(k, 0)) for k in parts) / max(1.0, sum(float(w.get(k, 0)) for k in parts))
    return round(total, 1), parts


def explain_score(parts: dict, line: dict) -> list[dict]:
    """Desglose del puntaje de línea: por componente, sus puntos, su peso (%) y cuánto aporta al total."""
    w = line.get("scoring") or {}
    total_w = max(1.0, sum(float(w.get(k, 0)) for k in parts))
    return [{"component": k, "points": parts[k], "weight_pct": round(100 * float(w.get(k, 0)) / total_w, 1),
             "contribution": round(parts[k] * float(w.get(k, 0)) / total_w, 1)} for k in parts]


def collect_offers(ws: Workspace, line: dict, say=print, use_linkedin: bool = True) -> tuple[list[dict], dict]:
    """Conectores en paralelo (cola idempotente diaria + cortacircuitos por fuente) y LinkedIn guiado por geo."""
    from datetime import date

    from .pipeline import run_parallel
    cache = ws.root / "data" / "cache"
    ctx = sources.SourceContext(cache, line, ws.db_path)
    jobs = {}
    for name in line.get("sources") or []:
        fetch = sources.get(name)
        if fetch:
            jobs[name] = (lambda f=fetch: f(ctx))
    results = run_parallel(jobs, ws.db_path, f"{date.today():%Y-%m-%d}", say=say)
    offers, stats = [], {}
    for name in jobs:
        res = results.get(name)
        telemetry.portal(name, res)
        if isinstance(res, list):
            offers += res
            stats[name] = len(res)
            say(f"  {name}: {len(res)} offers")
        else:
            stats[name] = res
            say(f"  {name}: {res}")
    if use_linkedin and (line.get("linkedin") or {}).get("enabled"):
        offers += _linkedin_offers(ws, line, say, stats)
    return offers, stats


def linkedin_plan(line: dict) -> list[tuple[str, str, str | None]]:
    """[(palabra, ubicación, país ISO o None)] de nivel país/supranacional; las ciudades se agregan si se satura."""
    li = line.get("linkedin") or {}
    geo_cfg = li.get("geo") or {}
    plan = []
    for k in li.get("keywords") or []:
        for loc in li.get("locations") or []:
            plan.append((k, loc, None))
        for code, name in (geo_cfg.get("countries") or {}).items():
            plan.append((k, name, code))
    return plan


def _linkedin_offers(ws: Workspace, line: dict, say, stats: dict) -> list[dict]:
    from playwright.sync_api import sync_playwright

    from .apply.search import Searcher
    from .geo import Geo
    li = line.get("linkedin") or {}
    geo_cfg = li.get("geo") or {}
    limit = int(li.get("max_per_search", 10))
    ttl = int(geo_cfg.get("revisit_hours", 72))
    base = "https://www.linkedin.com/jobs/search/?keywords={k}&location={l}&f_WT=2"
    geo = Geo(ws.db_path)
    queue = list(linkedin_plan(line))
    out, links, searches, skipped, expanded = [], [], 0, 0, set()
    searcher = Searcher(ws, headless=True, say=lambda *_: None)
    with sync_playwright() as pw:
        searcher.runner.pw = pw
        try:
            while queue:
                if searcher.linkedin.exhausted():      # tope de la guardia: no recorrer el resto del plan
                    say("  linkedin: search cap reached for this run/day; remaining plan postponed")
                    break
                kw, loc, country = queue.pop(0)
                geo_key = country or loc
                if not geo.due("linkedin", geo_key + "|" + loc, kw):
                    skipped += 1
                    continue
                u = base.format(k=quote_plus(kw), l=quote_plus(loc))
                try:
                    found = [x for x in searcher.expand(u, limit) if x != u]
                except Exception as e:
                    searcher.runner.ctx = None
                    found = []
                    if "perfil" in str(e) or "in use" in str(e).lower():
                        say(f"  linkedin: {str(e)[:160]}")
                        break
                searches += 1
                if searches == 1 and not found:
                    say("  linkedin: no results (session missing? run `cvtitan sesiones --solo linkedin`); skipped")
                    break
                geo.record("linkedin", geo_key + "|" + loc, kw, len(found), ttl)
                if country and "." in country:
                    telemetry.explored(cities=[loc.split(",")[0].strip()], countries=[loc.split(",")[-1].strip()])
                elif country:
                    telemetry.explored(countries=[loc])
                links += [x for x in found if x not in links]
                # Expansión por ciudades SOLO si la búsqueda nacional se saturó (hay más de lo que muestra).
                if country and len(found) >= limit and (country, kw) not in expanded:
                    expanded.add((country, kw))
                    for c in geo.cities(country, int(geo_cfg.get("min_population", 500_000)),
                                        int(geo_cfg.get("max_cities_per_country", 25))):
                        queue.append((kw, Geo.city_label(c) + ", " + loc, f"{country}.{c['geonameid']}"))
            for u in links:
                try:
                    raw = searcher.read_job(u)
                except Exception:
                    continue
                out.append({"source": "LinkedIn", "url": u, "apply_url": u, "title": raw.get("title"),
                            "company": raw.get("company"), "text": raw.get("text") or "", "regions": None,
                            "salary": {k: raw[k] for k in ("salary_min", "salary_max", "salary_currency",
                                                           "salary_period") if raw.get(k)}, "tags": []})
        finally:
            if searcher.runner.ctx:
                try:
                    searcher.runner.ctx.close()
                except Exception:
                    pass
    stats["linkedin"] = f"{len(out)} offers · {searches} searches · {skipped} skipped (explored recently)"
    say(f"  linkedin: {stats['linkedin']}")
    return out


def run(ws: Workspace, simulate: bool = True, say=print, use_linkedin: bool = True) -> dict:
    line = load_line(ws, "B")
    tax = Taxonomy.load(ws.taxonomy_path)
    profile = Profile.load(ws.profile_path, tax)
    db = DB(ws.db_path)
    settings = load_yaml(ws.settings_path) if ws.settings_path.exists() else {}
    fx = fx_mod.resolve(ws.root, settings)
    sal_cfg = line.get("salary") or {}
    out_dir = ws.root / "data" / "auto" / "B"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")

    say(f"[1/4] International sources (remote from {markets.active().country})")
    telemetry.stage("LINE B · GLOBAL", 1, 4, "Scanning job boards")
    telemetry.agent("TITAN-SCOUT", "ACTIVE", f"{len(line.get('sources') or [])} sources"
                    + (" + LinkedIn" if use_linkedin else ""))
    offers, stats = collect_offers(ws, line, say, use_linkedin)
    if "linkedin" in stats:
        li = stats["linkedin"]
        telemetry.portal("linkedin", [None] * li if isinstance(li, int) else str(li))
    telemetry.count("discovered", len(offers))
    telemetry.market([{"source": o.get("source", "").split(" (")[0], "company": o.get("company"),
                       "modality": "remote" if o.get("regions") else ("on-site" if o.get("onsite") else None)}
                      for o in offers])
    telemetry.explored(companies=[o.get("company") or "" for o in offers])
    telemetry.agent("TITAN-SCOUT", "READY", f"{len(offers)} offers")
    telemetry.stage("LINE B · GLOBAL", 2, 4, "Role filter and de-duplication")
    telemetry.agent("TITAN-SHIELD", "ACTIVE", "checking registry and duplicates")

    say("\n[2/4] Role filter and de-duplication")
    history = {fingerprint(r.get("company"), r.get("title")) for r in db.list() if r["status"] in PROCESS_STATUSES}
    applied_urls = {r.get("url") for r in db.list() if r["status"] in PROCESS_STATUSES}
    from .registry import Registry
    registry = Registry(ws.db_path, worker="linea-b")
    seen, candidates, counts = set(), [], Counter()
    early: list[dict] = []                          # embudo: ofertas que no llegan a evaluarse

    def drop(o, reason):
        early.append({"line": "B", "stage": "filter", "tier": "no", "reason": reason, "reason_category": reason,
                      "title": o.get("title"), "company": o.get("company"), "source": o.get("source"),
                      "url": o.get("url")})
    for o in offers:
        if not o.get("title") or not o.get("url"):
            continue
        if not title_matches(o["title"], o.get("tags"), line):
            counts["off-target role"] += 1
            drop(o, "off-target role")
            continue
        fp = fingerprint(o.get("company"), o["title"])
        if fp in seen:
            counts["duplicate across boards"] += 1
            continue
        seen.add(fp)
        if fp in history or o["url"] in applied_urls:
            counts["already sent"] += 1
            continue
        v = registry.register(o["url"], o.get("company"), o["title"], None, None, "remoto", source=o["source"],
                              text=(o.get("text") or "")[:20000])
        if v["status"] in ("SUBMITTED_CONFIRMED", "SUBMISSION_UNKNOWN"):
            counts["already sent"] += 1       # vacante repetida: ya está lista, no se vuelve a enviar
            continue
        ok, why = registry.can_submit(v["id"])
        if not ok:
            counts["already reviewed"] += 1
            continue
        o["_vid"] = v["id"]
        candidates.append(o)
    from .colors import GREEN, paint
    done = counts.pop("already sent", 0)
    telemetry.count("done_before", done)
    telemetry.count("duplicates", counts.get("duplicate across boards", 0)
                    + counts.get("already reviewed", 0))
    telemetry.funnel(early)
    say(f"  {len(offers)} offers -> {len(candidates)} candidates ({dict(counts)})")
    if done:
        say("  " + paint(f"[DONE] {done} repeated job(s) already sent: marked as done, not re-sent", GREEN))

    say("\n[3/4] Eligibility, fit, salary and scoring")
    telemetry.stage("LINE B · GLOBAL", 3, 4, "Eligibility, fit and scoring")
    telemetry.agent("TITAN-MATCH", "ACTIVE", f"evaluating {len(candidates)} offers")
    # Vacantes de agregadores que exigen cuenta: buscar la MISMA vacante en el ATS público del empleador
    # (Greenhouse / Lever / Ashby). Si aparece, se postula ahí y su ubicación oficial manda.
    gated = set(line.get("board_account_required") or []) - set(line.get("board_accounts") or [])
    to_resolve = [o for o in candidates if o.get("company") and o["source"] in
                  (gated | {"Jobicy", "Arbeitnow"})]
    if to_resolve:
        from concurrent.futures import ThreadPoolExecutor
        cache = ws.root / "data" / "cache"
        with ThreadPoolExecutor(max_workers=16) as pool:
            found = list(pool.map(lambda o: intl_sources.resolve_employer_job(cache, o["company"], o["title"]),
                                  to_resolve))
        hits = 0
        for o, r in zip(to_resolve, found):
            if r:
                hits += 1
                o["apply_url"] = r["url"]
                o["ats"] = r["ats"]
                # Misma vacante: la URL del ATS se suma como fuente (el registro la reconoce y no la duplica).
                ats_v = registry.register(r["url"], o.get("company"), o["title"], None, None, "remoto", source=r["ats"])
                if ats_v["status"] in ("SUBMITTED_CONFIRMED", "SUBMISSION_UNKNOWN", "CLOSED", "PENDING_REVIEW"):
                    o["_known"] = ats_v["status"]      # ya enviada o ya descartada en el formulario del empleador
                loc = (r.get("location") or "").strip()
                if loc and not re.fullmatch(r"(?i)\s*remote\s*", loc):
                    o["ats_regions"] = [loc]
        say(f"  Employer ATS resolved: {hits}/{len(to_resolve)} (Greenhouse/Lever/Ashby, no account needed)")

    rows = []
    for o in candidates:
        text_elig = remote_eligibility(o["text"], None, "remoto")
        region_elig = intl_sources.region_eligibility(o.get("regions"))
        elig = region_elig or text_elig
        if o.get("ats_regions"):                      # la ubicación oficial del ATS del empleador manda
            ats_elig = intl_sources.region_eligibility(o["ats_regions"])
            if ats_elig:
                region_elig = elig = ats_elig.replace("restricción publicada por el portal", "ubicación oficial del empleador")
        if "patrocinio" in text_elig:
            # En remoto desde Chile no se necesita visa: «no sponsorship» no prueba que exijan residir allá.
            # Pero NUNCA rebaja una región oficial que ya excluye (p. ej. «Remote Canada»).
            text_elig = "ambiguo: menciona que no patrocina visas"
            if not region_elig:
                elig = text_elig
        tm = TITLE_PLACE.search(o["title"] or "")
        if tm and not elig.startswith("excluido"):
            elig = f"excluido: el título restringe a {tm.group(0).strip(' -()/,')}"
        if elig.startswith("ok") and text_elig.startswith("excluido"):   # el texto contradice la región: gana lo estricto
            elig = f"excluido: conflicto región/texto — {text_elig[10:]}"
        if o.get("onsite") and not re.search("(?i)" + markets.active().home_regex, o["onsite"]):
            # Escáner mundial (portal ATS del empleador): ubicación oficial presencial fuera de Chile.
            elig = f"excluido: presencial en {o['onsite'][:60]} (ubicación oficial del empleador)"
        job = job_intel.analyze(o["text"] or o["title"], tax, title=o["title"], company=o.get("company"),
                                url=o["url"], job_id="linea-b", meta=o.get("salary") or {})
        m = evidence.match(job, profile, tax)
        usd = _monthly_usd(o.get("salary") or {}, fx)
        score, parts = score_line(m, len(m["rows"]), elig, usd, m["years"]["ok"],
                                  (m["years"]["required"], m["years"]["candidate"]), line)
        gaps = [r["name"] for r in m["rows"] if r["status"] != "backed" and r["importance"] == "required"]
        if o.get("_known"):
            decision, why = "descartada", f"already handled on the employer's form ({o['_known']})"
        elif elig.startswith("excluido"):
            decision, why = "descartada", elig
        elif usd is not None and usd < float(sal_cfg.get("min_monthly", 3000)):
            decision, why = "descartada", f"sueldo publicado USD {usd:,.0f}/mes < {sal_cfg.get('min_monthly', 3000)}"
        elif o.get("ats") in (line.get("human_step_ats") or []):
            decision, why = "requiere persona", f"{o['ats']} exige CAPTCHA en cada postulación (no se automatiza)"
        elif o["source"] in gated and not o.get("ats"):
            decision, why = "en espera", f"{o['source']} exige cuenta del portal y no hallé la vacante en el ATS del empleador"
        elif score < float(line.get("min_score", 50)):
            decision, why = "descartada", f"puntaje {score} < {line.get('min_score', 50)}"
        else:
            decision, why = "postular", f"puntaje {score} · {elig.split(':')[0]}"
        rows.append({"decision": decision, "motivo": why, "score_linea": score, "compatibilidad": parts["compatibility"],
                     "pts_elegibilidad": parts["eligibility"], "pts_sueldo": parts["salary"],
                     "pts_experiencia": parts["experience"],
                     "elegibilidad": elig, "sueldo_usd_mes": f"{usd:,.0f}" if usd else "", "cargo": o["title"],
                     "empresa": o.get("company") or "", "fuente": o["source"],
                     "regiones": ", ".join(o.get("regions") or [])[:80], "idioma": job.get("language") or "",
                     "nivel": job.get("seniority") or "", "brechas": ", ".join(gaps[:5]),
                     "url": o.get("apply_url") or o["url"]})
        if o.get("ats"):
            rows[-1]["fuente"] = f"{o['source']} -> {o['ats']}"
    for o, r in zip(candidates, rows):                 # estado en el registro global (cobertura y trazabilidad)
        registry.set_status(o["_vid"], "QUALIFIED" if r["decision"] == "postular" else
                            ("CLOSED" if r["decision"] == "descartada" else "DISCOVERED"))
    rows.sort(key=lambda r: (r["decision"] != "postular", -float(r["score_linea"])))
    chosen = [r for r in rows if r["decision"] == "postular"]
    cap = int(line.get("daily_max", 10))
    for r in chosen[cap:]:
        r["decision"], r["motivo"] = "en espera", f"tope diario ({cap}); queda para la próxima ejecución"
    chosen = chosen[:cap]

    path = out_dir / f"{stamp}-decisiones.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter=";")
        w.writeheader()
        w.writerows(rows)
    elig_counts = Counter(r["elegibilidad"].split(":")[0] for r in rows)
    from .apply.legal import countries_in
    from .utils import normalize as _norm
    regions_txt = [" ".join(o.get("regions") or []) for o in candidates]
    from .apply.legal import COUNTRY_EN
    telemetry.explored(countries=[COUNTRY_EN.get(c, c).replace("the ", "") for t in regions_txt for c in countries_in(_norm(t))]
                       + (["Global/LATAM"] if any(re.search(r"(?i)worldwide|anywhere|latam|latin", t)
                                                  for t in regions_txt) else []))
    telemetry.count("analyzed", len(rows))
    telemetry.market([{"fit": r["score_linea"], "salary_usd": (r["sueldo_usd_mes"] or "").replace(",", "") or None}
                      for r in rows])
    telemetry.STATE.market_total -= len(rows)            # ya contadas al descubrirlas
    from .funnel import reason_category, tier_line_b
    margin = float(line.get("potential_margin", 10))
    records = []
    for r in rows:
        tier = tier_line_b(r["decision"], r["motivo"], float(r["score_linea"]), float(line.get("min_score", 50)), margin)
        r["nivel"] = tier
        records.append({"line": "B", "stage": "scored", "tier": tier, "reason": r["motivo"],
                        "reason_category": reason_category(r["motivo"]), "score": r["score_linea"],
                        "title": r["cargo"], "company": r["empresa"], "source": r["fuente"],
                        "modality": "remote", "url": r["url"],
                        "pts_compatibility": r["compatibilidad"], "pts_eligibility": r["pts_elegibilidad"],
                        "pts_salary": r["pts_sueldo"], "pts_experience": r["pts_experiencia"]})
    telemetry.funnel(records)
    telemetry.agent("TITAN-MATCH", "READY", f"{len(rows)} analyzed · {len(chosen)} compatible")
    say(f"  eligibility: {ELIG_EN(elig_counts)} · to apply: {len(chosen)} · details: {path}")
    for r in chosen:
        from .colors import decision as _dec
        say("   " + _dec("postular", f"{r['score_linea']:>5}  {r['cargo'][:55]} — {r['empresa'][:25]} [{r['fuente']}] "
            f"{('USD ' + r['sueldo_usd_mes'] + '/mes') if r['sueldo_usd_mes'] else ''}"))

    result = {"stats": stats, "offers": len(offers), "candidates": len(candidates), "rows": len(rows),
              "chosen": len(chosen), "eligibility": dict(elig_counts), "filtered": dict(counts), "decisions": str(path),
              "summary": []}
    from . import send_policy
    decision = send_policy.decide(line, simulate, max(1, len(chosen)), label="Line B")
    if not decision.send:
        say("\n[4/4] No submissions: " + ("simulation." if simulate else "Line B has send_enabled: false (requires your authorization)."))
        telemetry.stage("LINE B · GLOBAL", 4, 4, "Simulation · no submissions" if simulate else "Sending disabled")
        return result

    from .apply.batch import BatchApplier
    say(f"\n[4/4] Applying to {len(chosen)} international job(s)...")
    telemetry.stage("LINE B · GLOBAL", 4, 4, "Processing applications")
    applier = BatchApplier(ws, headless=True, force=True, auto_submit=decision.auto_submit, unattended=True,
                           login_window=False, say=say)
    result["summary"] = applier.run([r["url"] for r in chosen], limit=len(chosen), direct=True)
    for r in chosen:                                   # marca el mercado en el historial
        prev = db.find_by_url(r["url"])
        if prev:
            db.update_data(prev["job_id"], market="internacional", line="B")
    return result
