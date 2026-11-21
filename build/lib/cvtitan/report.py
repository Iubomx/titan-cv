"""Informe final de la ejecución e historial de postulaciones, 100 % texto (sin íconos).

- `mission_report(snapshot, hist)`: resumen de la ejecución recién terminada: totales, portales consultados,
  sitios visitados (por dominio) y cada vacante procesada con su resultado y URL.
- `history_report(db_path, days)`: historial persistente de postulaciones (data/cvtitan.db).
Ambos devuelven texto plano; la CLI lo imprime y lo guarda en data/auto/runs/<fecha>-report.txt.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from pathlib import Path

OUTCOME = {"ok": "SENT", "done": "DONE", "pend": "PEND", "no": "SKIP", "err": "FAIL"}


def term_width(default: int = 110) -> int:
    import shutil
    return max(100, min(220, shutil.get_terminal_size((default, 40)).columns - 1))


def _table(headers: list[str], rows: list[list[str]], widths: list[int], full: tuple[int, ...] = ()) -> list[str]:
    """Tabla ASCII. Las columnas en `full` (p. ej. URL) nunca se recortan."""
    def cell(v: str, w: int, keep: bool = False) -> str:
        v = " ".join(str(v).split())
        if keep:
            return v.ljust(w)
        return (v[: w - 3] + "...") if len(v) > w else v.ljust(w)
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [sep, "| " + " | ".join(cell(h, w) for h, w in zip(headers, widths)) + " |", sep]
    out += ["| " + " | ".join(cell(v, w, i in full) for i, (v, w) in enumerate(zip(r, widths))) + " |" for r in rows]
    out.append(sep)
    return out


def _title(text: str, width: int) -> list[str]:
    return ["", text.upper(), "=" * min(width, len(text) + 4)]


def mission_report(s: dict, hist: dict | None = None, width: int | None = None) -> str:
    hist = hist or {}
    width = width or term_width()
    c = s.get("counters", {})
    elapsed = time.time() - s.get("started", time.time())
    m, sec = divmod(int(elapsed), 60)
    h, m = divmod(m, 60)
    lines = ["=" * width, "TITAN CV - MISSION REPORT".center(width), "=" * width,
             f"Mission : {s.get('mission') or '-'}",
             f"Mode    : {(s.get('mode') or '-').upper()}",
             f"Finished: {datetime.now():%Y-%m-%d %H:%M:%S}   Duration: {h:02d}:{m:02d}:{sec:02d}",
             f"Status  : {s.get('stage') or '-'}"]

    lines += _title("1. Totals", width)
    totals = [("Offers discovered", c.get("discovered")), ("Offers analyzed", c.get("analyzed")),
              ("Compatible offers", c.get("compatible")), ("Applications confirmed (new)", c.get("applied")),
              ("Applications pending", c.get("pending")), ("Already sent (not repeated)", c.get("done_before")),
              ("Duplicates avoided", c.get("duplicates")), ("Offers discarded", c.get("discarded")),
              ("Errors", c.get("errors")), ("Companies detected", s.get("companies")),
              ("Countries explored", len(s.get("countries") or []) or None),
              ("Cities explored", len(s.get("cities") or []) or None)]
    lines += [f"  {k:<32} {('-' if v in (None, '') else f'{v:,}'):>8}" for k, v in totals]
    if hist:
        lines.append(f"  {'Sent today (all runs)':<32} {hist.get('today', 0):>8}")
        lines.append(f"  {'Sent in total (history)':<32} {hist.get('total', 0):>8}")

    portals = s.get("portals") or {}
    if portals:
        lines += _title("2. Job boards and sources queried", width)
        rows = [[name, f"{v:,}" if isinstance(v, int) else "-", "OK" if isinstance(v, int) else str(v)[:60]]
                for name, v in sorted(portals.items(), key=lambda kv: -(kv[1] if isinstance(kv[1], int) else -1))]
        lines += _table(["Source", "Offers", "Status"], rows, [28, 8, width - 50])

    visited = s.get("visited") or {}
    if visited:
        lines += _title(f"3. Sites visited ({len(visited)} domains, {sum(visited.values()):,} pages)", width)
        rows = [[d, f"{n:,}"] for d, n in sorted(visited.items(), key=lambda kv: -kv[1])]
        lines += _table(["Domain", "Pages"], rows, [width - 20, 10])

    processed = s.get("processed") or []
    if processed:
        lines += _title(f"4. Applications processed ({len(processed)})", width)
        from .privacy import mask_url
        rows = [[p["time"], OUTCOME.get(p["outcome"], "-"), p.get("title") or "-",
                 mask_url(p["url"]) if p.get("url") else "-",
                 p["result"].split(":", 1)[-1].strip()] for p in processed]
        rows = [[r[0], r[1], r[2], r[4], r[3]] for r in rows]          # URL al final, completa
        lines += _table(["Time", "Result", "Job", "Detail", "REF"], rows, [8, 6, 30, 40, max(20, width - 104)], full=(4,))
        for tag in ("SENT", "PEND", "FAIL"):
            n = sum(1 for p in processed if OUTCOME.get(p["outcome"]) == tag)
            if n:
                lines.append(f"  {tag}: {n}")

    alerts = [a for a in s.get("alerts") or [] if a[1] == "error"]
    if alerts:
        lines += _title("5. Errors", width)
        lines += [f"  {ts}  {text[:width - 12]}" for ts, _, text in alerts[-15:]]
    lines += ["", "-" * width, "Pending items: cvtitan postular --pendientes --ver   |   History: cvtitan informe --historial",
              "=" * width]
    return "\n".join(lines)


def history_report(db_path: Path, days: int | None = None, width: int | None = None) -> str:
    """Historial persistente de postulaciones enviadas (y su estado de proceso)."""
    from .db import DB, PROCESS_STATUSES
    width = width or term_width()
    rows = [r for r in DB(db_path).list() if r.get("status") in PROCESS_STATUSES]
    if days:
        since = (date.today() - timedelta(days=days)).isoformat()
        rows = [r for r in rows if str(r.get("applied_at") or "") >= since]
    rows.sort(key=lambda r: str(r.get("applied_at") or ""), reverse=True)
    lines = ["=" * width, "TITAN CV - APPLICATION HISTORY".center(width), "=" * width,
             f"Applications: {len(rows)}" + (f" (last {days} days)" if days else " (all time)"), ""]
    from .privacy import mask_url
    table = [[str(r.get("applied_at") or "")[:16].replace("T", " "), r.get("status") or "-",
              r.get("company") or "-", r.get("title") or "-", mask_url(r["url"]) if r.get("url") else "-"]
             for r in rows]
    lines += _table(["Date", "Status", "Company", "Job", "REF"], table, [16, 9, 20, 32, max(20, width - 94)], full=(4,))
    by_day: dict[str, int] = {}
    for r in rows:
        d = str(r.get("applied_at") or "")[:10]
        by_day[d] = by_day.get(d, 0) + 1
    if by_day:
        lines += ["", "Per day:"] + [f"  {d}  {n:>3}" for d, n in sorted(by_day.items(), reverse=True)[:14]]
    lines.append("=" * width)
    return "\n".join(lines)


# ---------------------------------------------------------------- informe con el estilo del centro de mando
def save_snapshot(s: dict, hist: dict, path: Path) -> None:
    """Guarda lo necesario para volver a dibujar el informe (sin URLs reales ni eventos completos)."""
    import json

    from .privacy import mask_url, redact
    keep = {k: s.get(k) for k in ("started", "mission", "mode", "stage", "finished", "counters", "portals",
                                  "visited", "market", "salaries", "market_total", "countries", "cities", "reasons",
                                  "cache_reads")}
    keep["processed"] = [{**{k: v for k, v in p.items() if k != "url"},
                          "ref": mask_url(p["url"]) if p.get("url") else "-",
                          "title": redact(p.get("title") or ""), "result": redact(p.get("result") or "")}
                         for p in s.get("processed") or []]
    keep["alerts"] = [(ts, lvl, redact(t)) for ts, lvl, t in (s.get("alerts") or []) if lvl == "error"]
    keep["ended"] = time.time()
    path.write_text(json.dumps({"snapshot": keep, "history": hist}, ensure_ascii=False, default=str), encoding="utf-8")


def render_mission(s: dict, hist: dict | None = None):
    """Mismo informe, como paneles Rich con la paleta del centro de mando. URLs solo como dominio + código."""
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    from .privacy import mask_url
    from .ui.theme import BG, BOX, CRIT, GREY, MATRIX, NEON, SUCCESS, WARN, WHITE

    hist = hist or {}
    c = s.get("counters", {})

    def panel(body, title, border=MATRIX):
        return Panel(body, title=Text(f"[ {title} ]", style=f"bold {NEON}"), title_align="left",
                     border_style=border, box=BOX, style=BG, padding=(0, 1))

    def kv(rows):
        t = Table.grid(expand=True, padding=(0, 2))
        t.add_column(style=WHITE, no_wrap=True)
        t.add_column(justify="right", style=f"bold {NEON}", no_wrap=True)
        for k, v in rows:
            t.add_row(k, "-" if v in (None, "", 0) else (f"{v:,}" if isinstance(v, int) else str(v)))
        return t

    elapsed = int((s.get("ended") or time.time()) - s.get("started", time.time()))
    head = Text()
    head.append("TITAN CV // MISSION REPORT   ", style=f"bold {NEON}")
    head.append(f"{s.get('mission') or '-'}  ::  {(s.get('mode') or '-').upper()}  ::  ", style=WHITE)
    head.append(f"T+{elapsed // 3600:02d}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}  ", style=WHITE)
    head.append(s.get("stage") or "-", style=SUCCESS if s.get("finished") else WARN)
    parts = [Panel(head, border_style=NEON, box=BOX, style=BG)]

    grid = Table.grid(expand=True, padding=(0, 1))
    for _ in range(3):
        grid.add_column(ratio=1)
    totals = kv([("Offers discovered", c.get("discovered")), ("Offers analyzed", c.get("analyzed")),
                 ("Compatible (all rules)", c.get("compatible")), ("  held by quota/registry", c.get("held_quota")),
                 ("  apply manually (portal)", c.get("manual_apply")), ("Potential (near score)", c.get("potential")),
                 ("On hold (account/CAPTCHA)", c.get("on_hold")), ("Applications SENT", c.get("applied")),
                 ("Pending (needs you)", c.get("pending")),
                 ("Duplicates avoided", (c.get("duplicates") or 0) + (c.get("done_before") or 0)),
                 ("Not compatible", c.get("discarded")), ("Errors", c.get("errors"))])
    m, total = s.get("market") or {}, s.get("market_total") or 0
    sal = sorted(s.get("salaries") or [])
    market = kv([("Offers in market", total), ("Sources", len(m.get("source") or {})),
                 ("Companies", len(m.get("company") or {})), ("Countries", len(m.get("country") or {})),
                 ("Cities", len(m.get("city") or {})), ("Salary published", len(sal)),
                 ("Median salary (USD/mo)", f"{sal[len(sal) // 2]:,.0f}" if sal else None),
                 ("Live pages fetched", sum((s.get("visited") or {}).values())),
                 ("Live domains", len(s.get("visited") or {})), ("Cached source reads", s.get("cache_reads"))])
    memory = kv([("Sent today (all runs)", hist.get("today")), ("Sent, confirmed by platform", hist.get("confirmed")),
                 ("Already applied (detected)", hist.get("already_applied")), ("History total", hist.get("total")),
                 ("Registry jobs", (hist.get("registry") or {}).get("vacancies")),
                 ("Multi-board duplicates", (hist.get("registry") or {}).get("multi_source")),
                 ("Daily quota", hist.get("daily_max"))])
    grid.add_row(panel(totals, "MISSION METRICS"), panel(market, "MARKET INTEL"), panel(memory, "MEMORY"))
    parts.append(grid)

    reasons = s.get("reasons") or {}
    if reasons:
        t = Table(box=None, expand=True, header_style=f"bold {GREY}", pad_edge=False)
        t.add_column("NOT COMPATIBLE - REASON", style=WHITE)
        t.add_column("OFFERS", justify="right", style=f"bold {NEON}")
        t.add_column("SHARE", justify="right", style=GREY)
        tot = sum(reasons.values())
        for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
            t.add_row(k, f"{v:,}", f"{100 * v / tot:.1f}%")
        parts.append(panel(t, "DISCARD REASONS"))

    portals = s.get("portals") or {}
    if portals:
        t = Table(box=None, expand=True, header_style=f"bold {GREY}", pad_edge=False)
        t.add_column("SOURCE", style=WHITE)
        t.add_column("OFFERS", justify="right", style=f"bold {NEON}")
        t.add_column("STATUS", style=GREY)
        for name, v in sorted(portals.items(), key=lambda kv: -(kv[1] if isinstance(kv[1], int) else -1)):
            t.add_row(name, f"{v:,}" if isinstance(v, int) else "-", "OK" if isinstance(v, int) else str(v)[:50])
        parts.append(panel(t, "SOURCES"))

    processed = s.get("processed") or []
    if processed:
        styles = {"ok": SUCCESS, "done": SUCCESS, "pend": WARN, "no": GREY, "err": CRIT}
        t = Table(box=None, expand=True, header_style=f"bold {GREY}", pad_edge=False)
        for col, kw in (("TIME", {"width": 8}), ("RESULT", {"width": 6}), ("JOB", {"ratio": 3}),
                        ("REF", {"ratio": 2}), ("DETAIL", {"ratio": 3})):
            t.add_column(col, no_wrap=True, overflow="ellipsis", **kw)
        for p in processed:
            st = styles.get(p["outcome"], WHITE)
            t.add_row(p["time"], Text(OUTCOME.get(p["outcome"], "-"), style=f"bold {st}"), p.get("title") or "-",
                      Text(p.get("ref") or (mask_url(p["url"]) if p.get("url") else "-"), style=MATRIX),
                      Text(p["result"].split(":", 1)[-1].strip(), style=GREY))
        parts.append(panel(t, f"APPLICATIONS PROCESSED ({len(processed)})"))

    errors = [a for a in s.get("alerts") or [] if a[1] == "error"]
    if errors:
        parts.append(panel(Text("\n".join(f"{ts}  {text[:120]}" for ts, _, text in errors[-10:]), style=CRIT),
                           "ERRORS", CRIT))
    parts.append(Text("  Pending: cvtitan postular --pendientes --ver  |  History: cvtitan informe --historial  |  "
                      "Decode a REF: cvtitan informe --ref JOB-XXXXXXXX", style=GREY))
    return Group(*parts)
