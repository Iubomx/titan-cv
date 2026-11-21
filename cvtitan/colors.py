"""Colores y etiquetas de texto: [SENT] enviada, [DONE] ya enviada antes, [PEND] pendiente, [SKIP] no aplica,
[FAIL] error.

Se desactiva solo si la salida no es una terminal (p. ej. --log a archivo) o si existe NO_COLOR.
"""
from __future__ import annotations

import os
import sys

# Paleta profesional (24 bits): verde = éxito, ámbar = pendiente, rojo = error, gris = secundario, azul = acento.
GREEN, YELLOW, RED, GREY, CYAN, BOLD, RESET = ("\033[38;2;76;195;138m", "\033[38;2;229;184;66m",
                                              "\033[38;2;229;83;75m", "\033[38;2;138;147;160m",
                                              "\033[38;2;95;179;249m", "\033[1m", "\033[0m")


def _enable() -> bool:
    if os.environ.get("NO_COLOR") or not getattr(sys.stdout, "isatty", lambda: False)():
        return False
    if sys.platform == "win32":                       # activar secuencias ANSI en la consola de Windows (PowerShell 5.1)
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if k.GetConsoleMode(h, ctypes.byref(mode)):
                k.SetConsoleMode(h, mode.value | 0x0004)
        except Exception:
            return False
    return True


ON = _enable()


def paint(text: str, color: str) -> str:
    return f"{color}{text}{RESET}" if ON else text


def kind(result: str) -> str:
    """Clasifica el resultado de una postulación: ok (enviada ahora) | done (ya enviada antes) | pend | no | err."""
    r = (result or "").lower().strip()
    if r.startswith(("done", "lista", "ya postulada")) or "already applied" in r or "ya postulaste" in r:
        return "done"                         # ya estaba postulada antes: no es un envío nuevo
    if r.startswith("applied") or "application submitted" in r or "postulación enviada" in r:
        return "ok"
    if r.startswith(("error", "stopped", "detenida")):
        return "err"
    if r.startswith(("pending", "pendiente", "awaiting", "needs_input", "not sent", "no enviada"))             or "awaiting human review" in r or "esperando revisión" in r:
        return "pend"
    return "no"                               # skipped, discarded, cancelled…


MARKS = {"ok": ("[SENT]", GREEN), "done": ("[DONE]", GREEN), "no": ("[SKIP]", GREY), "pend": ("[PEND]", YELLOW),
         "err": ("[FAIL]", RED)}


def mark(result: str, text: str | None = None) -> str:
    """Línea con su etiqueta y color ([SENT] en verde si se postuló)."""
    sym, color = MARKS[kind(result)]
    return paint(f"{sym} {text if text is not None else result}", color)


def decision(dec: str, text: str) -> str:
    """Marca para la selección (antes de postular)."""
    d = (dec or "").lower()
    if d == "postular":
        return paint(f"[MATCH] {text}", CYAN)
    if d in ("en espera", "requiere persona"):
        return paint(f"[HOLD]  {text}", YELLOW)
    return paint(f"[DROP]  {text}", GREY)


def tally(results: list[str]) -> str:
    c = {"ok": 0, "done": 0, "no": 0, "pend": 0, "err": 0}
    for r in results:
        c[kind(r)] += 1
    return " | ".join([paint(f"applied {c['ok']}", GREEN), paint(f"already sent {c['done']}", GREEN),
                       paint(f"pending {c['pend']}", YELLOW), paint(f"not applicable {c['no']}", GREY),
                       paint(f"errors {c['err']}", RED)])


def status_bar(done: int, total: int, results: list[str], sent_today: int | None = None, width: int = 24) -> str:
    """Barra de estado en vivo: progreso del lote + CV enviados (y total del día)."""
    c = {"ok": 0, "done": 0, "no": 0, "pend": 0, "err": 0}
    for r in results:
        c[kind(r)] += 1
    filled = int(width * done / total) if total else width
    bar = "[" + paint("#" * filled, GREEN) + paint("-" * (width - filled), GREY) + "]"
    pct = int(100 * done / total) if total else 100
    parts = [f"{bar} {done}/{total} {pct:>3}%", paint(f"sent {c['ok']}", GREEN + BOLD),
             paint(f"done {c['done']}", GREEN), paint(f"pending {c['pend']}", YELLOW), paint(f"skipped {c['no']}", GREY)]
    if c["err"]:
        parts.append(paint(f"errors {c['err']}", RED))
    if sent_today is not None:
        parts.append(paint(f"today: {sent_today}", CYAN))
    return " | ".join(parts)


def set_title(text: str) -> None:
    """Título de la ventana de la terminal (contador visible aunque la ventana esté minimizada en la barra)."""
    if not ON:
        return
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(text)
        else:
            sys.stdout.write(f"\033]0;{text}\007")
    except Exception:
        pass
