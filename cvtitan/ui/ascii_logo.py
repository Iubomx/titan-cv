"""Logotipo TITAN CV: nombre sobre el casco espartano frontal (generado a partir de la imagen del casco)."""

HELMET_LARGE = """         ████████
         ▀██████
       ▄▄▄██████▄▄
     ▄██████████████▄
    ██████████████████
  ▄████████████████████▄
  ██████████████████████
  ██████████████████████
  ███▀ ▀██████████▀ ▀███
 ▄███▄    ▀████▀    ████▄
 ▀██████▄▄█ ██ █▄▄██████▀
   ██████▀ ███  ▀█████▀
    ████▀   ▀▀   ▀████
    ████          ████
    █████        █████
     ████        ████
      ▀██▄      ▄██▀
       ▀██      ██▀
         █     ▄█
          ▀    ▀
"""

HELMET_SMALL = """      ██████
      ▄████▄
   ▄██████████▄
  ▄████████████▄
 ████████████████
 ▀██▀████████▀██▀
 ███  ▀▀██▀▀  ███
 ▀█████▀██▀█████▀
  ▀███  ▀▀  ███
   ███      ███
   ███      ██▀
    ▀██    ██▀
     ▀█    █▀
"""

# Fuente de píxeles para el nombre (se dibuja con medios bloques: 2 píxeles por carácter en vertical).
FONT = {
    "T": ["#####", "..#..", "..#..", "..#..", "..#.."],
    "I": ["###", ".#.", ".#.", ".#.", "###"],
    "A": [".##.", "#..#", "####", "#..#", "#..#"],
    "N": ["#..#", "##.#", "#.##", "#..#", "#..#"],
    "C": [".###", "#...", "#...", "#...", ".###"],
    "V": ["#...#", "#...#", "#...#", ".#.#.", "..#.."],
    " ": ["..", "..", "..", "..", ".."],
}


def block_text(word: str) -> list[str]:
    """Texto grande con medios bloques (3 filas de alto)."""
    cols = [FONT[ch] for ch in word.upper() if ch in FONT]
    rows = ["." .join(g[r] for g in cols) for r in range(5)] + ["." * len(".".join(g[0] for g in cols))]
    out = []
    for r in range(0, 6, 2):
        top, bot = rows[r], rows[r + 1]
        out.append("".join("█" if t == "#" and b == "#" else "▀" if t == "#" else "▄" if b == "#" else " "
                           for t, b in zip(top, bot)).rstrip())
    return out


def figlet_title(text: str = "TITAN CV", font: str = "ansi_shadow") -> list[str]:
    """Título grande con PyFiglet para la pantalla de arranque; si no está instalado, usa la fuente de bloques."""
    try:
        import pyfiglet
        art = pyfiglet.figlet_format(text, font=font, width=200)
        return [line.rstrip() for line in art.rstrip().splitlines()]
    except Exception:
        return block_text(text)


def materialize(art: str, progress: float = 1.0, scan_row: int | None = None, seed: int | None = None):
    """Casco como texto Rich animable.
    progress: fracción de filas ya «materializadas» (las demás se ven como 0/1 en verde apagado).
    scan_row: fila resaltada por la línea de escaneo (None = sin escaneo)."""
    import random

    from rich.text import Text

    from .theme import DIM, MATRIX, NEON, WHITE
    rng = random.Random(seed)
    rows = art.rstrip("\n").split("\n")
    shown = int(round(max(0.0, min(1.0, progress)) * len(rows)))
    t = Text(no_wrap=True)
    for r, line in enumerate(rows):
        if r < shown:
            style = f"bold {NEON}" if r == scan_row else WHITE
            t.append(line, style=style)
        elif r == shown:                                   # frente de materialización
            t.append("".join(ch if ch == " " else rng.choice("01") for ch in line), style=f"bold {NEON}")
        else:
            t.append("".join(ch if ch == " " else rng.choice("01") for ch in line), style=DIM if r > shown + 1 else MATRIX)
        if r < len(rows) - 1:
            t.append("\n")
    return t
