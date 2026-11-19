"""Casco TITAN formado por CÓDIGO REAL, vivo: aparece escaneándose, pulsa, tiene glitch suave y el código fluye
dentro de la silueta.

- Máscara (0/1) separada del motor: generada a partir de la imagen del logo (casco frontal espartano).
- Relleno: líneas reales del código fuente de TITAN CV (sus propios módulos), con respaldo en CODE_FALLBACK.
- Motor: `HelmetAnimator.frame(t, reveal)` devuelve un `rich.text.Text`. Parámetros: velocidad del flujo,
  intensidad del glitch, vaivén y paleta.
Solo texto: sin íconos.
"""
from __future__ import annotations

import math
import random
import re
from functools import lru_cache
from pathlib import Path

from rich.text import Text

from .theme import CRIT, DIM, MATRIX, NEON, WHITE

CYAN = "#9FD3FF"          # brillo del escáner y destellos (azul claro)

MASK_LARGE = (
    "00000000000001111111111110000000000000",
    "00000000000001111111111100000000000000",
    "00000000000000111111111100000000000000",
    "00000000000000111111111100000000000000",
    "00000000001111111111111111110000000000",
    "00000001111111111111111111111100000000",
    "00000011111111111111111111111111000000",
    "00000111111111111111111111111111100000",
    "00011111111111111111111111111111110000",
    "00011111111111111111111111111111111000",
    "00011111111111111111111111111111111000",
    "00011111011111111111111111111111111000",
    "00011111001111111111111111100011110000",
    "00011111000000111111111100000011111000",
    "00111111100000001111100000001111111100",
    "00111111111111110111101111111111111100",
    "00001111111111100111100111111111110000",
    "00000111111110000111100011111101100000",
    "00000111111100000011000001111111000000",
    "00000011111100000000000000111111000000",
    "00000011111100000000000001111111000000",
    "00000011111110000000000001111111000000",
    "00000001111110000000000001111110000000",
    "00000000111110000000000011111100000000",
    "00000000011111000000000011110000000000",
    "00000000000111000000000111100000000000",
    "00000000000011100000000111000000000000",
    "00000000000001100000000100000000000000",
)

MASK_SMALL = (
    "00000000011111111000000000",
    "00000000011111110000000000",
    "00000000011111111000000000",
    "00000011111111111111000000",
    "00001111111111111111110000",
    "00011111111111111111111000",
    "00111111111111111111111100",
    "00111111111111111111111100",
    "00111101111111111110111100",
    "00111100001111110000111100",
    "01111111001011010011111110",
    "00011111110111001111111000",
    "00001111100011000111110000",
    "00001111000000000011110000",
    "00001111100000000111110000",
    "00000111100000000111100000",
    "00000011100000001111000000",
    "00000001110000001110000000",
    "00000000010000001000000000",
)


# Módulos de TITAN CV cuyo código rellena el casco (texto real del sistema).
CODE_MODULES = ("line_b.py", "autopilot.py", "registry.py", "apply/legal.py", "apply/question_bank.py",
                "apply/batch.py", "telemetry.py", "job_dictionary.py")
CODE_FALLBACK = (
    "score_line(m, n_skills, elig, usd, years_ok, years, line)", "remote_eligibility(text, country, modality)",
    "registry.claim(vacancy_id)", "global_search(latam=True, remote=True)", "duplicate_check(hash_id)",
    "apply_if_approved(job_id)", "SELECT * FROM vacancies WHERE status = 'QUALIFIED'",
    "react typescript python fastapi sql server", "discover filter score apply", "telemetry.publish(event)",
)


@lru_cache(maxsize=1)
def code_corpus() -> str:
    """Una sola cadena con código real de TITAN CV (líneas no vacías, sin comentarios ni docstrings)."""
    root = Path(__file__).resolve().parents[1]
    lines: list[str] = []
    for rel in CODE_MODULES:
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        text = re.sub(r'"""[\s\S]*?"""', "", text)
        for ln in text.splitlines():
            s = ln.strip()
            if len(s) > 12 and not s.startswith(("#", "from ", "import ")):
                lines.append(re.sub(r"\s+", " ", s))
    lines = lines or list(CODE_FALLBACK)
    corpus = "  ".join(lines)
    return "".join(ch if ch.isascii() and ch.isprintable() else " " for ch in corpus)


class HelmetAnimator:
    """Casco animado. El CONTORNO de la silueta se dibuja siempre firme (alto contraste, desplazamiento máximo de
    ±1 columna), así que la forma del casco nunca se pierde; los efectos agresivos van al INTERIOR:
    ráfagas de glitch, corrupción de caracteres, separación de color cian/rojo, banda de escaneo y parpadeo.

    reveal 0..1: aparición por escáner de arriba hacia abajo. still=True: casco quieto (fin de la misión).
    intensity 0..1: agresividad de los efectos (0 = sobrio, 1 = máximo)."""

    GLITCH_CHARS = r"#%@&$!?/\|[]{}<>01=+*"

    def __init__(self, mask: tuple[str, ...] = MASK_LARGE, flow_speed: float = 18.0, glitch: float = 0.012,
                 sway: float = 1.0, intensity: float = 0.7, seed: int | None = None):
        self.mask = mask
        self.flow_speed = flow_speed
        self.glitch = glitch
        self.sway = sway
        self.intensity = max(0.0, min(1.0, intensity))
        self.rng = random.Random(seed)
        self.corpus = code_corpus()
        self.width = max(len(r) for r in mask)
        self.height = len(mask)
        cell = lambda x, y: 0 <= y < self.height and 0 <= x < len(mask[y]) and mask[y][x] == "1"  # noqa: E731
        # Borde = celda llena con algún vecino vacío: define la forma y se dibuja siempre con alto contraste.
        self.edge = {(x, y) for y, row in enumerate(mask) for x, c in enumerate(row)
                     if c == "1" and not all(cell(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))}

    def _burst(self, t: float) -> float:
        """0..1: fuerza de la ráfaga de glitch (ráfagas cortas y periódicas, más seguidas con más intensidad)."""
        if self.intensity <= 0:
            return 0.0
        period = 2.2 - 1.2 * self.intensity
        phase = (t % period) / period
        return max(0.0, 1 - phase / 0.16) if phase < 0.16 else 0.0

    def frame(self, t: float, reveal: float = 1.0, still: bool = False) -> Text:
        if still:
            t, reveal = 0.0, 1.0
        h, rng, corpus, k = self.height, self.rng, self.corpus, self.intensity
        live = reveal >= 1.0 and not still
        scan = reveal * (h + 2) - 1
        burst = self._burst(t) if live else 0.0
        offset = int(t * self.flow_speed) + (rng.randrange(400) if burst > 0.5 else 0)   # salto del flujo en la ráfaga
        band = (t * 11) % (h + 10) - 4 if live else -99                                  # banda de escaneo (3 filas)
        flicker = live and rng.random() < 0.03 * k                                       # parpadeo del interior
        flash = live and rng.random() < 0.025 * k                                        # destello cian del contorno
        # Filas desplazadas durante la ráfaga (interior desplazado; el borde se mueve como mucho ±1).
        torn = {}
        if burst > 0:
            for _ in range(1 + int(3 * k * burst)):
                y0 = rng.randrange(h)
                for y in range(y0, min(h, y0 + rng.randint(1, 3))):
                    torn[y] = rng.choice((-3, -2, 2, 3))
        p_corrupt = self.glitch + (0.10 * k * burst)
        out = Text(no_wrap=True)
        pad = int(self.sway) + 3
        for y, row in enumerate(self.mask):
            base = int(round(math.sin(t * 2.6 + y * 0.33) * self.sway)) if live else 0
            edge_shift = max(-1, min(1, base + (1 if y in torn else 0) * (1 if torn.get(y, 0) > 0 else -1)))
            line = [(" ", "")] * (self.width + 2 * pad)
            for x, c in enumerate(row):
                if c != "1":
                    continue
                is_edge = (x, y) in self.edge
                if not live and not still and y > scan:                         # aún sin escanear
                    if rng.random() < 0.18:
                        line[x + pad] = (rng.choice("01"), DIM)
                    continue
                ch = corpus[(offset + y * 97 + x + (torn.get(y, 0) * 7 if not is_edge else 0)) % len(corpus)]
                if ch == " ":
                    ch = "#" if is_edge else ":"
                if still:
                    style = f"bold {NEON}" if is_edge else MATRIX
                elif not live:                                                   # aparición por escáner
                    d = scan - y
                    style = f"bold {WHITE}" if abs(d) < 1 else f"bold {CYAN}" if d < 2.5 else \
                        (f"bold {NEON}" if is_edge else MATRIX)
                elif is_edge:                                                    # contorno: siempre firme
                    style = f"bold {CYAN}" if flash else f"bold {WHITE}" if abs(y - band) < 1.5 else f"bold {NEON}"
                else:                                                            # interior: aquí va el caos
                    if rng.random() < p_corrupt:
                        ch = rng.choice(self.GLITCH_CHARS)
                        style = rng.choice((f"bold {CRIT}", f"bold {CYAN}", f"bold {WHITE}"))
                    elif abs(y - band) < 1.5:
                        style = f"bold {WHITE}"
                    elif flicker:
                        style = DIM
                    else:
                        glow = (math.sin(t * 5.0 + x * 0.3 + y * 0.2) + 1) / 2
                        style = NEON if glow > 0.7 else MATRIX if glow > 0.3 else DIM
                xx = x + pad + (edge_shift if is_edge else base + torn.get(y, 0))
                if 0 <= xx < len(line):
                    line[xx] = (ch, style)
                # Separación de color (aberración cromática) junto al borde durante la ráfaga, fuera de la silueta.
                if is_edge and burst > 0.3 and rng.random() < 0.5 * k:
                    gx = xx + rng.choice((-1, 1))
                    if 0 <= gx < len(line) and line[gx][0] == " ":
                        line[gx] = (rng.choice(r"|/\:"), CYAN if gx < xx else CRIT)
            for ch, style in line:
                out.append(ch, style=style or None)
            if y < h - 1:
                out.append("\n")
        return out
