"""Portada del CLI: logo TITAN CV (nombre arriba, casco espartano abajo) con la paleta profesional."""
from __future__ import annotations

import sys

from .colors import ON
from .ui.ascii_logo import HELMET_LARGE, block_text

NEON, WHITE, YELLOW, RESET = ("\033[38;2;95;179;249m", "\033[38;2;230;233;239m", "\033[38;2;138;147;160m",
                              "\033[0m")   # azul acero, blanco suave, gris


def show(subtitle: str = "", out=None, effect: str = "unstable") -> None:
    """Imprime el logo solo en una terminal interactiva (no ensucia los registros --log)."""
    out = out or sys.stdout
    if not getattr(out, "isatty", lambda: False)():
        return
    title = block_text("TITAN CV")
    helmet = HELMET_LARGE.rstrip().splitlines()
    width = max(len(line) for line in title + helmet)

    def paint(text: str, color: str) -> str:
        return f"{color}{text}{RESET}" if ON else text

    def block(lines: list[str]) -> list[str]:          # centra el dibujo completo, sin deformarlo
        pad = " " * ((width - max(len(line) for line in lines)) // 2)
        return [pad + line for line in lines]

    if out is sys.stdout:                            # efecto TTE (glitch que se reordena); si no, dibujo simple
        from .ui.text_effects import play
        art = "\n".join(["  " + ln for ln in block(title)] + [""] + ["  " + ln for ln in block(helmet)])
        if play(art, effect):
            if subtitle:
                out.write("\n  " + paint(subtitle.center(width), YELLOW) + "\n\n")
            out.flush()
            return
    out.write("\n")
    for line in block(title):
        out.write("  " + paint(line, NEON) + "\n")
    out.write("\n")
    import time
    for line in block(helmet):                       # el casco se dibuja línea a línea (animación de carga)
        out.write("  " + paint(line, WHITE) + "\n")
        out.flush()
        time.sleep(0.025)
    if subtitle:
        out.write("\n  " + paint(subtitle.center(width), YELLOW) + "\n")
    out.write("\n")
    out.flush()
