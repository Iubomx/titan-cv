"""Piloto automático: busca, filtra por las reglas de config/auto.yaml y postula sin preguntar.

    cvtitan auto              -> ciclo completo (busca + postula)
    cvtitan auto --simular    -> mismo filtro, pero NO postula (muestra a cuáles postularía)

Cada ejecución deja data/auto/<fecha-hora>.csv con TODAS las vacantes y la decisión tomada (y su motivo).
Reglas fijas que no se pueden desactivar: solo skills respaldadas en el CV, nunca crear cuentas, nunca
resolver CAPTCHA ni escribir contraseñas (si un portal lo pide, se abre una ventana o queda pendiente).
"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path

from . import markets
from .db import DB, PROCESS_STATUSES as PROCESS
from .utils import PACKAGE_ROOT, Workspace, load_yaml, normalize

AUTO_PATH = PACKAGE_ROOT / "config" / "auto.yaml"


def load_rules(ws: Workspace) -> dict:
    path = ws.root / "config" / "auto.yaml"
    rules = load_yaml(path if path.exists() else AUTO_PATH)
    flat = lambda p: re.sub(r"\s*\|\s*", "|", (p or "").strip())   # noqa: E731  (patrones en varias líneas)
    rules["_include"] = {k: re.compile(flat(v)) for k, v in (rules.get("include") or {}).items()}
    rules["_exclude"] = re.compile(flat(rules.get("exclude"))) if rules.get("exclude") else None
    if rules.get("dictionary_priorities"):
        from .job_dictionary import title_regex
        rules["_include"]["diccionario"] = re.compile(title_regex(rules["dictionary_priorities"]))
    return rules


def decide(row: dict, rules: dict, prefs: dict) -> tuple[bool, str]:
    """¿Postular a esta fila del listado? Devuelve (sí/no, motivo)."""
    title = normalize(row.get("cargo") or "")
    manual = [normalize(x) for x in rules.get("manual_platforms") or []]
    if normalize(row.get("plataforma") or "") in manual or any(m in (row.get("url") or "") for m in manual):
        return False, f"{row.get('plataforma')} bloquea la automatización: postula a mano si te interesa"
    if rules["_exclude"] and rules["_exclude"].search(title):
        return False, f"cargo excluido ({rules['_exclude'].search(title).group(0)})"
    families = [k for k, rx in rules["_include"].items() if rx.search(title)]
    if not families:
        return False, "cargo fuera de tus roles"
    elig = row.get("elegibilidad") or ""
    if elig.startswith("excluido"):
        return False, f"no se puede trabajar desde Chile: {elig[10:]}"
    contract = row.get("contrato") or ""
    temporary = bool(contract or re.search(
        r"por proyecto|\(proyecto\)|- proyecto|plazo fijo|freelance|reemplazo|temporal|part.?time", title))
    part_time = bool(row.get("jornada")) or bool(re.search(r"part.?time|medio tiempo|freelance|por horas", title))
    remote = normalize(row.get("modalidad") or "") == "remoto" or "remot" in title
    side_job = temporary and part_time and remote          # proyecto remoto y de pocas horas: sí sirve
    if rules.get("exclude_temporary", True) and temporary and not (rules.get("allow_remote_part_time", True)
                                                                    and side_job):
        return False, f"trabajo {contract or 'por proyecto o temporal'} (no es remoto de pocas horas)"
    score = float(row.get("score") or 0)
    if score < float(rules.get("min_score", 55)):
        return False, f"ajuste {score:g} < {rules.get('min_score', 55)}"
    if rules.get("salary_rule") == "minimo" and not side_job and str(row.get("vs_pretension", "")).startswith("bajo"):
        return False, f"sueldo {row['vs_pretension']}"
    return True, f"{', '.join(families)} · ajuste {score:g}" + (" · remoto de pocas horas" if side_job else "")


def applied_today(db: DB) -> int:
    today = date.today().isoformat()
    # Solo cuentan los envíos del robot: las detectadas como «ya postulaste» no consumen cupo.
    return sum(1 for r in db.list() if r["status"] == "applied" and str(r.get("applied_at") or "").startswith(today)
               and "ya postulaste" not in (r.get("status_detail") or "")
               and "already applied" not in (r.get("status_detail") or ""))


def run(ws: Workspace, simulate: bool = False, say=print, reuse: Path | None = None) -> dict:
    from .apply.batch import BatchApplier
    from .apply.search import run_search
    from .profile import Profile
    from .taxonomy import Taxonomy

    rules = load_rules(ws)
    tax = Taxonomy.load(ws.taxonomy_path)
    prefs = Profile.load(ws.profile_path, tax).data.get("preferences") or {}
    db = DB(ws.db_path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out_dir = ws.root / "data" / "auto" / "A"
    out_dir.mkdir(parents=True, exist_ok=True)

    from . import telemetry
    telemetry.stage(markets.active().stage_name, 1, 3, markets.active().scan_label)
    telemetry.agent("TITAN-SCOUT", "ACTIVE", markets.active().agent_label)
    if reuse:
        say(f"[1/3] Using saved search {reuse}")
        rows = list(csv.DictReader(reuse.read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))
        rows = [r for r in rows if (db.find_by_url(r["url"]) or {}).get("status") not in PROCESS]
    else:
        say(f"[1/3] Searching job openings (groups: {', '.join(rules.get('groups') or [])})...")
        where = list(markets.active().local_sources)
        _, rows = run_search(ws, [], where, markets.active().country, [], int(rules.get("max_per_search", 8)),
                             out_dir / f"{stamp}-busqueda.csv", headless=True, groups=rules.get("groups"), say=say)

    telemetry.count("discovered", len(rows))
    telemetry.market([{"source": r.get("plataforma"), "company": r.get("empresa"), "country": r.get("pais") or markets.active().country,
                       "city": r.get("ciudad"), "modality": r.get("modalidad"), "fit": r.get("score")} for r in rows])
    by_portal: dict = {}
    for r in rows:
        by_portal[r.get("plataforma") or "?"] = by_portal.get(r.get("plataforma") or "?", 0) + 1
    for name, n in by_portal.items():
        telemetry.portal(name, [None] * n)
    telemetry.explored(countries=[r.get("pais") or "" for r in rows], cities=[r.get("ciudad") or "" for r in rows],
                       companies=[r.get("empresa") or "" for r in rows])
    telemetry.agent("TITAN-SCOUT", "READY", f"{len(rows)} offers")
    telemetry.stage(markets.active().stage_name, 2, 3, "Rules, fit and scoring")
    telemetry.agent("TITAN-MATCH", "ACTIVE", f"evaluating {len(rows)} offers")
    say("\n[2/3] Applying your rules...")
    quota = max(0, int(rules.get("daily_max", 15)) - applied_today(db))
    from .registry import Registry
    registry = Registry(ws.db_path, worker="linea-a")
    chosen: list[dict] = []
    for r in rows:
        ok, why = decide(r, rules, prefs)
        known = registry.by_url(r.get("url") or "") if ok else None
        if known:
            allowed, reason = registry.can_submit(known["id"])
            if not allowed:
                ok, why = False, f"registry: {reason}"
        if ok and len(chosen) >= quota:
            ok, why = False, f"daily cap reached ({rules.get('daily_max', 15)})"
        r["decision"] = "postular" if ok else "descartada"
        r["motivo"] = why
        if ok:
            chosen.append(r)
    decision_csv = out_dir / f"{stamp}-decisiones.csv"
    cols = ["decision", "nivel", "motivo", "score", "cargo", "empresa", "pais", "modalidad", "contrato", "salario",
            "vs_pretension", "plataforma", "url"]
    with decision_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["decision"] != "postular", -float(r.get("score") or 0))))
    say(f"  {len(chosen)} match your rules (today's quota: {quota}) · details: {decision_csv}")
    telemetry.count("analyzed", len(rows))
    from .funnel import reason_category, tier_line_a
    no_manual = {**rules, "manual_platforms": []}
    margin = float(rules.get("potential_margin", 10))
    records = []
    for r in rows:
        score = float(r.get("score") or 0)
        manual_ok = "bloquea la automat" in (r.get("motivo") or "") and decide(r, no_manual, prefs)[0]
        tier = tier_line_a(r["decision"], r.get("motivo", ""), score, float(rules.get("min_score", 55)), margin,
                           manual_ok)
        r["nivel"] = tier
        records.append({"line": "A", "stage": "scored", "tier": tier, "reason": r.get("motivo", ""),
                        "reason_category": reason_category(r.get("motivo", "")), "score": score,
                        "title": r.get("cargo"), "company": r.get("empresa"), "source": r.get("plataforma"),
                        "country": r.get("pais"), "modality": r.get("modalidad"), "url": r.get("url")})
    telemetry.funnel(records)
    telemetry.agent("TITAN-MATCH", "READY", f"{len(rows)} analyzed · {len(chosen)} compatible")
    for r in chosen:
        say("   " + __import__("cvtitan.colors", fromlist=["decision"]).decision(
            "postular", f"{float(r['score']):>5.1f}  {r['cargo'][:60]} — {r.get('empresa') or '?'}"))

    # Cola de reintentos: vacantes que quedaron en «queued» (p. ej. tras una corrección del robot).
    seen_urls = {r.get("url") for r in chosen}
    for q in db.list():
        if len(chosen) >= quota:
            break
        if q.get("status") != "queued" or not q.get("url") or q["url"] in seen_urls:
            continue
        known = registry.by_url(q["url"])
        if known and not registry.can_submit(known["id"])[0]:
            continue
        chosen.append({"cargo": q.get("title") or "", "empresa": q.get("company") or "", "score": q.get("score") or 0,
                       "url": q["url"], "plataforma": q.get("platform") or "", "decision": "postular",
                       "motivo": "retry queue"})
        seen_urls.add(q["url"])
        say(f"  retry queue: {(q.get('title') or q['url'])[:70]}")
    result = {"found": len(rows), "chosen": len(chosen), "decisions": str(decision_csv), "summary": []}
    from . import send_policy
    from .line_b import load_line
    try:
        line_cfg = load_line(ws, "A")
    except ValueError:                                   # sin línea A configurada: no se envía nada
        line_cfg = {}
    decision = send_policy.decide(line_cfg, simulate, len(chosen), label="Line A")
    if not decision.send:
        say("\n[3/3] " + decision.reason)
        telemetry.stage(markets.active().stage_name, 3, 3, decision.stage_label)
        return result

    say(f"\n[3/3] Applying to {len(chosen)} job(s)...")
    telemetry.stage(markets.active().stage_name, 3, 3, "Processing applications")
    applier = BatchApplier(ws, headless=True, force=True, auto_submit=decision.auto_submit, unattended=True,
                           login_window=False, say=say)
    result["summary"] = applier.run([r["url"] for r in chosen], limit=len(chosen), direct=True)
    with (out_dir / f"{stamp}-resultado.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["vacante", "score", "resultado"])
        w.writerows(result["summary"])
    return result
