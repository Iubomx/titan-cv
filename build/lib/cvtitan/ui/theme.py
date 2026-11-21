"""Paleta y estilos del centro de mando TITAN CV: sobria y profesional.
Acento azul acero; blanco suave para lo importante; gris para lo secundario; verde solo para éxito,
ámbar para advertencias y rojo para errores. (Los nombres NEON/MATRIX se conservan por compatibilidad.)"""
from __future__ import annotations

from rich import box
from rich.theme import Theme

BLACK = "#0C0F14"         # fondo grafito
NEON = "#5FB3F9"          # acento principal: azul acero (títulos, bordes activos, estados ACTIVE)
MATRIX = "#3E7CB1"        # acento secundario
DIM = "#26323F"           # bordes y rellenos apagados
WHITE = "#E6E9EF"         # texto principal
GREY = "#8A93A0"          # texto secundario
SUCCESS = "#4CC38A"       # éxito (postulación confirmada)
WARN = "#E5B842"          # advertencias
CRIT = "#E5534B"          # errores
BG = f"on {BLACK}"

BOX = box.SQUARE          # bordes de línea simple, se ven bien en CMD, PowerShell y Windows Terminal

AGENT_STATUS = {          # estado -> (marca de texto, estilo)
    "ONLINE": ("*", f"bold {NEON}"),
    "ACTIVE": ("*", f"bold {NEON}"),
    "READY": ("+", MATRIX),
    "STANDBY": ("-", GREY),
    "OFFLINE": ("-", GREY),
    "ALERT": ("!", f"bold {WARN}"),
    "ERROR": ("x", f"bold {CRIT}"),
}
LEVEL = {"info": ("INFO", MATRIX), "warn": ("WARN", WARN), "error": ("FAIL", CRIT), "debug": ("DBG ", GREY)}

RICH_THEME = Theme({"neon": NEON, "matrix": MATRIX, "dim": DIM, "warn": WARN, "crit": CRIT, "white": WHITE,
                    "grey": GREY, "success": SUCCESS})
