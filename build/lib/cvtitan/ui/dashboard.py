"""TITAN CV · Hacker Command Center (Rich Live + Layout).

Solo PRESENTACIÓN. Todo lo que se dibuja proviene de:
  - `cvtitan.telemetry`   estado real informado por el motor (contadores, agentes, fases, eventos)
  - `EventStream`         ritmo de eventos del bus (sin bloquear al motor)
  - `SystemMonitor`       consumo real de recursos (psutil)
  - `history_provider`    historial persistente (data/cvtitan.db) y registro antiduplicados
Nada se inventa: lo que el motor no informó se muestra como «—».

Modos (funciones legítimas de la aplicación, ver `cvtitan auto --modo`):
  HUNTER MODE · GLOBAL SCAN · AI ANALYSIS · APPLY MODE · STEALTH UI · DEBUG MODE
"""
from __future__ import annotations

import io
import platform
import sys
import time
from typing import Callable

from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .. import telemetry
from .ascii_helmet import MASK_LARGE, MASK_SMALL, HelmetAnimator
from .ascii_logo import block_text
from .event_stream import EventStream
from .system_monitor import SystemMonitor, human_bytes
from .theme import AGENT_STATUS, BG, BOX, CRIT, DIM, GREY, LEVEL, MATRIX, NEON, SUCCESS, WARN, WHITE

MODES = {
    "hunter": ("HUNTER MODE", "discover opportunities in Chile (no submissions)"),
    "global": ("GLOBAL SCAN", "international remote exploration (no submissions)"),
    "analysis": ("AI ANALYSIS", "full scoring of both lines (no submissions)"),
    "apply": ("APPLY MODE", "authorized application processing"),
    "stealth": ("STEALTH UI", "minimal text interface"),
    "debug": ("DEBUG MODE", "technical diagnostics"),
    "showcase": ("SHOWCASE", "SIMULATED DATA - demonstration only"),
}


def _panel(body, title: str, border: str = MATRIX) -> Panel:
    return Panel(body, title=Text(f"[ {title} ]", style=f"bold {NEON}"), title_align="left",
                 border_style=border, box=BOX, style=BG, padding=(0, 1))


def _bar(done: int, total: int, width: int, color: str = NEON) -> Text:
    width = max(6, width)
    ratio = (done / total) if total else 0.0
    fill = int(round(ratio * width))
    t = Text(no_wrap=True)
    t.append("[", style=DIM)
    t.append("#" * fill, style=color)
    t.append("-" * (width - fill), style=DIM)
    t.append("]", style=DIM)
    t.append(f" {done}/{total}" if total else " —", style=WHITE)
    if total:
        t.append(f" {int(ratio * 100):>3}%", style=GREY)
    return t


def _pct_bar(pct: float | None, width: int = 12) -> Text:
    if pct is None:
        return Text("—", style=GREY)
    fill = int(round(min(100.0, pct) / 100 * width))
    color = CRIT if pct >= 90 else WARN if pct >= 70 else NEON
    t = Text(no_wrap=True)
    t.append("[", style=DIM)
    t.append("|" * fill, style=color)
    t.append("." * (width - fill), style=DIM)
    t.append("]", style=DIM)
    t.append(f" {pct:5.1f}%", style=WHITE)
    return t


def _elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _cursor() -> str:
    return "█" if int(time.time() * 2) % 2 == 0 else " "


class _LogStream(io.TextIOBase):
    """Captura print()/stderr mientras el tablero está activo y lo convierte en eventos."""

    def __init__(self, level: str | None = None):
        self.level = level
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            telemetry.log(line, self.level)
        return len(s)

    def flush(self) -> None:
        if self._buf.strip():
            telemetry.log(self._buf, self.level)
        self._buf = ""

    def isatty(self) -> bool:
        return False


class CommandCenter:
    def __init__(self, mode: str = "apply", history_provider: Callable[[], dict] | None = None,
                 console: Console | None = None, refresh_per_second: float = 20, screen: bool = True,
                 monitor: SystemMonitor | None = None, helmet_opts: dict | None = None):
        self.mode = mode if mode in MODES else "apply"
        opts = helmet_opts or {}
        self.helmet_large = HelmetAnimator(MASK_LARGE, **opts)
        self.helmet_small = HelmetAnimator(MASK_SMALL, **opts)
        self._t0 = time.time()
        self.console = console or Console(file=sys.__stdout__, highlight=False, emoji=False)
        self.history_provider = history_provider
        self.refresh = refresh_per_second
        self.screen = screen
        self.monitor = monitor or SystemMonitor()
        self.stream = EventStream()
        self._history: dict = {}
        self._history_at = 0.0
        self._render_ms = 0.0
        self._live: Live | None = None
        self._saved = None

    # ---------------------------------------------------------------- ciclo de vida
    def __enter__(self) -> "CommandCenter":
        self.stream.start()
        self._saved = (sys.stdout, sys.stderr)
        sys.stdout, sys.stderr = _LogStream(), _LogStream("error")
        self._live = Live(get_renderable=self.render, console=self.console, screen=self.screen,
                          refresh_per_second=self.refresh, redirect_stdout=False, redirect_stderr=False)
        self._live.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            if self._saved:
                sys.stdout, sys.stderr = self._saved
            if self._live:
                self._live.__exit__(*exc)
            self.stream.stop()
            self._history_at = 0.0
            if self.screen:                       # foto final del tablero en la terminal normal
                self.console.print(self.render())

    # ---------------------------------------------------------------- datos
    def _hist(self) -> dict:
        if self.history_provider and time.time() - self._history_at > 5:
            try:
                self._history = self.history_provider() or {}
            except Exception as e:
                self._history = {"error": str(e)[:120]}
            self._history_at = time.time()
        return self._history

    # ---------------------------------------------------------------- dibujo
    def render(self) -> Layout:
        t0 = time.perf_counter()
        self.stream.drain()
        s = telemetry.snapshot()
        h = self._hist()
        sysm = self.monitor.sample()
        width, height = self.console.size
        debug = self.mode == "debug"

        root = Layout(name="root")
        side_w = 44 if width >= 120 else 0
        if side_w:
            root.split_row(Layout(self._logo(height), name="logo", size=side_w), Layout(name="main"))
            main = root["main"]
        else:
            root.split_column(Layout(self._logo_compact(), name="logo", size=5), Layout(name="main"))
            main = root["main"]

        main.split_column(
            Layout(self._header(s), name="header", size=3),
            Layout(name="top", size=16),
            Layout(self._progress(s, h, width - side_w), name="progress", size=6),
            Layout(name="bottom"),
        )
        wide = width - side_w >= 110
        if wide:
            main["top"].split_row(Layout(self._metrics(s), ratio=4), Layout(self._agents(s), ratio=5),
                                  Layout(self._radar(s, h), ratio=5))
            main["bottom"].split_row(Layout(self._events(s, height, debug), ratio=6), Layout(name="side", ratio=4))
            side = [Layout(self._market(s), size=14), Layout(self._system(s, sysm), size=10),
                    Layout(self._alerts(s), ratio=1)]
            if debug:
                side.append(Layout(self._debug(s), size=9))
            main["bottom"]["side"].split_column(*side)
        else:
            main["top"].split_row(Layout(self._metrics(s), ratio=1), Layout(self._agents(s), ratio=1))
            main["bottom"].split_row(Layout(self._events(s, height, debug), ratio=3), Layout(name="side", ratio=2))
            main["bottom"]["side"].split_column(Layout(self._radar(s, h), size=9), Layout(self._system(s, sysm), size=11),
                                                Layout(self._alerts(s), ratio=1))
        self._render_ms = (time.perf_counter() - t0) * 1000
        return root

    # ---------------------------------------------------------------- paneles
    def _logo(self, height: int) -> Panel:
        title = Text("\n".join(block_text("TITAN CV")), style=f"bold {NEON}")
        helmet = self.helmet_large if height >= 46 else self.helmet_small if height >= 32 else None
        parts = [Align.center(title), Text("")]
        if helmet:
            # Casco de código real: vivo durante la misión; al terminar queda quieto (sin flujo ni glitch).
            parts.append(Align.center(helmet.frame(time.time() - self._t0, 1.0, still=telemetry.STATE.finished)))
            parts.append(Text(""))
        modes = Table.grid(padding=(0, 1))
        modes.add_column(width=2)
        modes.add_column(no_wrap=True)
        for key, (label, _) in MODES.items():
            active = key == self.mode
            modes.add_row(Text(">" if active else " ", style=NEON),
                          Text(label, style=f"bold {NEON} reverse" if active else MATRIX))
        parts += [Align.center(Text("// OPERATION MODES //", style=GREY)), Align.center(modes), Text(""),
                  Align.center(Text(MODES[self.mode][1], style=WARN))]
        return Panel(Group(*parts), border_style=NEON, box=BOX, style=BG, padding=(1, 1))

    def _logo_compact(self) -> Panel:
        title = Text("\n".join(block_text("TITAN CV")), style=f"bold {NEON}")
        return Panel(Align.center(title), border_style=NEON, box=BOX, style=BG, padding=(0, 1))

    def _header(self, s: dict) -> Panel:
        t = Table.grid(expand=True)
        t.add_column(ratio=3, no_wrap=True, overflow="ellipsis")
        t.add_column(ratio=2, justify="right", no_wrap=True)
        left = Text()
        left.append("root@titan-cv", style=f"bold {NEON}")
        left.append(":~# ", style=MATRIX)
        left.append(MODES[self.mode][0], style=f"bold {WHITE}")
        if s["mission"]:
            left.append(f" :: {s['mission']}", style=NEON)
        left.append(f" :: {s['stage']}", style=WARN if not s["finished"] else NEON)
        left.append(" " + _cursor(), style=NEON)
        right = Text()
        right.append("MISSION COMPLETE  " if s["finished"] else "OPERATIONAL  ", style=f"bold {NEON}")
        right.append(f"T+{_elapsed(time.time() - s['started'])}  ", style=WHITE)
        right.append(time.strftime("%H:%M:%S"), style=GREY)
        t.add_row(left, right)
        return Panel(t, border_style=NEON, box=BOX, style=BG, padding=(0, 1))

    def _metrics(self, s: dict) -> Panel:
        c = s["counters"]
        t = Table.grid(expand=True, padding=(0, 1))
        t.add_column(style=WHITE, no_wrap=True, overflow="ellipsis", ratio=3)
        t.add_column(justify="right", no_wrap=True, ratio=1)
        styles = {"applied": f"bold {SUCCESS}", "pending": f"bold {WARN}", "errors": f"bold {CRIT}",
                  "discarded": GREY, "duplicates": MATRIX, "done_before": MATRIX}
        for key, label in telemetry.COUNTERS.items():
            val = c.get(key)
            if key == "duplicates" and ("duplicates" in c or "done_before" in c):
                val = c.get("duplicates", 0) + c.get("done_before", 0)
            t.add_row(label, Text("—" if val is None else f"{val:,}", style=styles.get(key, WHITE)))
        return _panel(t, "MISSION METRICS")

    def _agents(self, s: dict) -> Panel:
        t = Table.grid(expand=True, padding=(0, 1))
        t.add_column(width=1, no_wrap=True)
        t.add_column(no_wrap=True, min_width=12)
        t.add_column(no_wrap=True, min_width=7)
        t.add_column(style=GREY, overflow="ellipsis", no_wrap=True, ratio=1)
        for name in telemetry.AGENTS:
            st, detail = s["agents"].get(name, ("STANDBY", ""))
            icon, style = AGENT_STATUS.get(st, ("-", GREY))
            t.add_row(Text(icon, style=style), Text(name, style=f"bold {NEON}" if st == "ACTIVE" else WHITE),
                      Text(st, style=style), detail or telemetry.AGENTS[name])
        return _panel(t, "AGENTS")

    def _radar(self, s: dict, h: dict) -> Panel:
        t = Table.grid(expand=True, padding=(0, 1))
        t.add_column(style=WHITE, no_wrap=True)
        t.add_column(justify="right", style=f"bold {NEON}", no_wrap=True)
        ok = [k for k, v in s["portals"].items() if isinstance(v, int)]
        t.add_row("Portals", f"{len(ok)}/{len(s['portals'])}" if s["portals"] else "-")
        t.add_row("Countries", str(len(s["countries"])) if s["countries"] else "-")
        t.add_row("Cities", str(len(s["cities"])) if s["cities"] else "-")
        t.add_row("Companies", f"{s['companies']:,}" if s["companies"] else "-")
        reg = h.get("registry") or {}
        t.add_row("Registry", f"{reg['vacancies']:,}" if reg.get("vacancies") else "-")
        names = ", ".join(s["countries"][:8]) + ("..." if len(s["countries"]) > 8 else "")
        body = Group(t, Text(names, style=GREY, overflow="ellipsis", no_wrap=True)) if names else t
        return _panel(body, "COVERAGE")

    def _progress(self, s: dict, h: dict, width: int) -> Panel:
        bw = max(10, width - 44)
        t = Table.grid(expand=True, padding=(0, 1))
        t.add_column(style=WHITE, width=16, no_wrap=True)
        t.add_column(ratio=1, no_wrap=True)
        t.add_row("Mission phases", _bar(s["stage_n"], s["stage_total"], bw))
        t.add_row("Applications", _bar(s["apply_done"], s["apply_total"], bw))
        today, cap = h.get("today"), h.get("daily_max")
        t.add_row("Daily quota", _bar(today or 0, cap, bw, WARN if today and cap and today >= cap else NEON)
                  if cap else Text("—", style=GREY))
        t.add_row("Target", Text("> " + s["current"], style=WARN, overflow="ellipsis", no_wrap=True)
                  if s["current"] else Text("> -", style=GREY))
        return _panel(t, "PROGRESS")

    def _events(self, s: dict, height: int, debug: bool) -> Panel:
        n = max(5, height - 28)
        t = Table.grid(expand=True, padding=(0, 1))
        t.add_column(style=GREY, width=8, no_wrap=True)
        t.add_column(width=7, no_wrap=True)
        t.add_column(width=4, no_wrap=True)
        t.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
        for ts, lvl, line, agent in s["events"][-n:]:
            icon, color = LEVEL.get(lvl, LEVEL["info"])
            msg = Text.from_ansi(line.strip())
            if lvl != "info":
                msg.stylize(color)
            elif not msg.spans:
                msg.stylize(WHITE)
            t.add_row(ts, Text(agent.replace("TITAN-", ""), style=MATRIX), Text(icon, style=color), msg)
        if not s["events"]:
            t.add_row("", "", "", Text("Awaiting events…", style=GREY))
        title = f"EVENT STREAM · {self.stream.total} events · {self.stream.rate_per_min():.0f}/min"
        return _panel(t, title)

    def _market(self, s: dict) -> Panel:
        """Inteligencia de mercado: TODAS las ofertas analizadas (se postule o no), datos reales del motor."""
        m, total = s.get("market") or {}, s.get("market_total") or 0
        sal = sorted(s.get("salaries") or [])
        mod = m.get("modality") or {}
        remote = sum(v for k, v in mod.items() if "remot" in k.lower())
        t = Table.grid(expand=True, padding=(0, 1))
        t.add_column(style=WHITE, no_wrap=True)
        t.add_column(justify="right", style=f"bold {NEON}", no_wrap=True)
        t.add_column(style=GREY, no_wrap=True, overflow="ellipsis", ratio=1)
        top = lambda k, n=2: ", ".join(f"{a} {b}" for a, b in sorted((m.get(k) or {}).items(), key=lambda kv: -kv[1])[:n])  # noqa: E731
        t.add_row("Offers in market", f"{total:,}" if total else "-", "")
        t.add_row("Sources", str(len(m.get("source") or {})) or "-", top("source"))
        t.add_row("Companies", f"{len(m.get('company') or {}):,}" or "-", top("company"))
        t.add_row("Countries", str(len(m.get("country") or {})) or "-", top("country"))
        t.add_row("Cities", str(len(m.get("city") or {})) or "-", top("city"))
        t.add_row("Remote share", f"{100 * remote / total:.0f}%" if total else "-", f"{remote:,} remote")
        t.add_row("Salary published", f"{len(sal):,}", f"median USD {sal[len(sal) // 2]:,.0f}/mo" if sal else "")
        fit = m.get("fit") or {}
        n_fit = sum(fit.values())
        for label in ("80-100", "65-79", "50-64", "0-49"):
            n = fit.get(label, 0) + (fit.get("35-49", 0) + fit.get("0-34", 0) if label == "0-49" else 0)
            if n_fit:
                t.add_row(f"Fit {label}", f"{n:,}", Text("#" * max(0, int(18 * n / n_fit)), style=MATRIX))
        return _panel(t, "MARKET INTEL // REAL DATA")

    def _system(self, s: dict, m: dict) -> Panel:
        t = Table.grid(expand=True, padding=(0, 1))
        t.add_column(style=WHITE, no_wrap=True, width=12)
        t.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
        if not m:
            t.add_row("Resources", Text("— (psutil not installed)", style=GREY))
        else:
            t.add_row("System CPU", _pct_bar(m.get("sys_cpu")))
            t.add_row("System RAM", _pct_bar(m.get("sys_mem_pct")))
            t.add_row("TITAN", Text(f"{m.get('proc_cpu', 0):.0f}% CPU · {human_bytes(m.get('proc_mem'))} · "
                                    f"{m.get('threads', '—')} threads", style=NEON))
            t.add_row("Chrome", Text(f"{m.get('chrome_procs', 0)} procs · {human_bytes(m.get('chrome_mem'))}",
                                     style=NEON if m.get("chrome_procs") else GREY))
            if "net_down" in m:
                t.add_row("Network", Text(f"down {human_bytes(m['net_down'])}/s  up {human_bytes(m['net_up'])}/s", style=MATRIX))
            if "disk_free" in m:
                t.add_row("Disk free", Text(human_bytes(m["disk_free"]), style=MATRIX))
        for name, (st, detail) in s["system"].items():
            icon, style = AGENT_STATUS.get(st, ("-", GREY))
            t.add_row(name, Text(f"{st} {detail}", style=style))
        return _panel(t, "SYSTEM RESOURCES")

    def _alerts(self, s: dict) -> Panel:
        alerts = s["alerts"][-8:]
        errs = sum(1 for _, lvl, _ in s["alerts"] if lvl == "error")
        t = Table.grid(expand=True, padding=(0, 1))
        t.add_column(style=GREY, width=8, no_wrap=True)
        t.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
        for ts, lvl, text in reversed(alerts):
            t.add_row(ts, Text(("FAIL " if lvl == "error" else "WARN ") + text, style=CRIT if lvl == "error" else WARN))
        if not alerts:
            t.add_row("", Text("No alerts. All clear.", style=MATRIX))
        border = CRIT if errs else WARN if s["alerts"] else MATRIX
        return _panel(t, f"ALERTS · {len(s['alerts'])} · {errs} critical", border)

    def _debug(self, s: dict) -> Panel:
        t = Table.grid(expand=True, padding=(0, 1))
        t.add_column(style=GREY, no_wrap=True, width=14)
        t.add_column(style=WHITE, no_wrap=True, overflow="ellipsis", ratio=1)
        t.add_row("render", f"{self._render_ms:.1f} ms @ {self.refresh:g} fps")
        t.add_row("event queue", f"{self.stream.pending()} pending · {self.stream.total} total")
        t.add_row("by kind", ", ".join(f"{k}:{v}" for k, v in sorted(self.stream.by_kind.items())) or "—")
        t.add_row("active agent", s["active_agent"])
        t.add_row("runtime", f"Python {platform.python_version()} · {platform.system()} {platform.release()}")
        t.add_row("terminal", f"{self.console.size.width}×{self.console.size.height} · {self.console.color_system}")
        return _panel(t, "DEBUG", GREY)


def available() -> bool:
    """¿Se puede mostrar el centro de mando? (salida a una terminal real)."""
    return bool(getattr(sys.__stdout__, "isatty", lambda: False)())
