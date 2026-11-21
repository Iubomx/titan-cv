"""Arranque del centro de mando: lluvia binaria tipo Matrix y secuencia de inicio con comprobaciones REALES.

Cada línea «[ OK ]» del arranque es una verificación que de verdad se ejecuta (perfil, base de datos, Chrome,
configuración, motor de IA…). Dura unos segundos y se omite con `--sin-intro` o si la salida no es una terminal.
"""
from __future__ import annotations

import random
import time
from typing import Callable

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.text import Text


from .ascii_helmet import MASK_LARGE, MASK_SMALL, HelmetAnimator
from .ascii_logo import figlet_title
from .theme import CRIT, DIM, GREY, MATRIX, NEON, WARN, WHITE

Check = tuple[str, Callable[[], tuple[bool | None, str]]]   # (etiqueta, función -> (ok, detalle))


class MatrixRain:
    """Lluvia de 0/1 por columnas; cada columna cae a su propia velocidad."""

    def __init__(self, width: int, height: int, seed: int | None = None):
        self.w, self.h = max(10, width), max(5, height)
        self.rng = random.Random(seed)
        self.drops = [self.rng.randint(-self.h, 0) for _ in range(self.w)]
        self.speed = [self.rng.choice((1, 1, 2)) for _ in range(self.w)]
        self.trail = [self.rng.randint(4, max(5, self.h // 2)) for _ in range(self.w)]

    def step(self) -> None:
        for x in range(self.w):
            self.drops[x] += self.speed[x]
            if self.drops[x] - self.trail[x] > self.h:
                self.drops[x] = self.rng.randint(-self.h // 2, 0)
                self.speed[x] = self.rng.choice((1, 1, 2))

    def render(self) -> Text:
        t = Text(no_wrap=True, overflow="crop")
        for y in range(self.h):
            for x in range(self.w):
                d = self.drops[x] - y
                if d == 0:
                    t.append(self.rng.choice("01"), style=f"bold {WHITE}")
                elif 0 < d <= self.trail[x]:
                    t.append(self.rng.choice("01"), style=NEON if d < 3 else MATRIX if d < self.trail[x] // 2 + 2 else DIM)
                else:
                    t.append(" ")
            if y < self.h - 1:
                t.append("\n")
        return t


def _cursor() -> str:
    return "█" if int(time.time() * 2) % 2 == 0 else " "


def boot(console: Console, checks: list[Check], mode: str = "", rain_seconds: float = 1.4,
         helmet_opts: dict | None = None) -> list[tuple[str, bool | None, str]]:
    """Lluvia binaria + secuencia de arranque. Devuelve los resultados de las comprobaciones."""
    width, height = console.size
    rain = MatrixRain(width, height - 1)
    helmet = HelmetAnimator(MASK_LARGE if height >= 52 else MASK_SMALL, **(helmet_opts or {}))
    t0 = time.time()
    results: list[tuple[str, bool | None, str]] = []
    lines: list[Text] = []

    def boot_screen() -> Group:
        title = Text("\n".join(figlet_title()), style=f"bold {NEON}")
        progress = len(results) / max(1, len(checks))           # el casco se escanea con las comprobaciones
        body = [Align.center(title), Align.center(helmet.frame(time.time() - t0, progress)),
                Text(""), Align.center(Text(f"AUTONOMOUS JOB INTELLIGENCE SYSTEM · {mode or 'APPLY MODE'}",
                                            style=f"bold {WARN}")), Text("")]
        log = Text()
        for ln in lines:
            log.append_text(ln)
            log.append("\n")
        log.append("root@titan-cv:~# ", style=NEON)
        log.append(_cursor(), style=NEON)
        return Group(*body, log)

    with Live(rain.render(), console=console, screen=True, refresh_per_second=24, transient=True) as live:
        end = time.time() + rain_seconds
        while time.time() < end:
            rain.step()
            live.update(rain.render(), refresh=True)
            time.sleep(1 / 24)
        lines.append(Text(f"TITAN CV kernel · booting subsystems ({time.strftime('%Y-%m-%d %H:%M:%S')})", style=MATRIX))
        live.update(boot_screen(), refresh=True)
        for label, fn in checks:
            t0 = time.time()
            try:
                ok, detail = fn()
            except Exception as e:                       # una comprobación fallida no impide arrancar
                ok, detail = False, f"{type(e).__name__}: {e}"[:80]
            results.append((label, ok, detail))
            tag, style = ("[  OK  ]", NEON) if ok else ("[ WARN ]", WARN) if ok is None else ("[ FAIL ]", CRIT)
            ln = Text()
            ln.append(tag, style=f"bold {style}")
            ln.append(f" {label:<26}", style=WHITE)
            ln.append(f" {detail}", style=GREY)
            ln.append(f"  {int((time.time() - t0) * 1000)} ms", style=DIM)
            lines.append(ln)
            live.update(boot_screen(), refresh=True)
            time.sleep(0.12 if rain_seconds > 0.1 else 0)
        lines.append(Text("All subsystems initialized. Handing over to TITAN-CORE…", style=f"bold {NEON}"))
        for _ in range(6):                               # cursor parpadeando un instante antes del tablero
            live.update(boot_screen(), refresh=True)
            time.sleep(0.25 if rain_seconds > 0.1 else 0)
    return results
