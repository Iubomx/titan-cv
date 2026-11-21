"""Efectos de texto para la salida de terminal clásica (modo texto / stealth), con TerminalTextEffects (TTE).

TTE es la librería de efectos de terminal más completa de Python (decrypt, glitch, slice, matrix...). Se usa
solo para la portada y con efectos cortos medidos sobre el logo completo a 120 fps:
  unstable 2,1 s (glitch que se reordena) · slice 1,6 s · errorcorrect 3,0 s · decrypt 5,9 s
Si TTE no está instalado, la salida no es una terminal o algo falla, se devuelve False y la portada se
dibuja sin efecto. Paleta profesional: degradado azul acero -> blanco suave.
"""
from __future__ import annotations

import importlib
import sys

EFFECTS = {"unstable": ("unstable", "Unstable"), "slice": ("slice", "Slice"),
           "errorcorrect": ("errorcorrect", "ErrorCorrect"), "decrypt": ("decrypt", "Decrypt")}
STOPS = ("5FB3F9", "9FD3FF", "E6E9EF")         # azul acero -> azul claro -> blanco suave


def play(text: str, effect: str = "unstable", fps: int = 120) -> bool:
    """Reproduce `effect` sobre `text` en la terminal. True si se mostró."""
    if effect in (None, "", "none") or effect not in EFFECTS:
        return False
    if not getattr(sys.stdout, "isatty", lambda: False)():
        return False
    try:
        from terminaltexteffects import Color
        mod, cls = EFFECTS[effect]
        Effect = getattr(importlib.import_module(f"terminaltexteffects.effects.effect_{mod}"), cls)
        e = Effect(text)
        e.terminal_config.frame_rate = fps
        if hasattr(e.effect_config, "final_gradient_stops"):
            e.effect_config.final_gradient_stops = tuple(Color(c) for c in STOPS)
        if hasattr(e.effect_config, "unstable_color"):
            e.effect_config.unstable_color = Color("E5534B")
        if hasattr(e.effect_config, "ciphertext_colors"):
            e.effect_config.ciphertext_colors = (Color("3E7CB1"), Color("5FB3F9"), Color("26323F"))
        with e.terminal_output() as terminal:
            for frame in e:
                terminal.print(frame)
        return True
    except Exception:
        return False
