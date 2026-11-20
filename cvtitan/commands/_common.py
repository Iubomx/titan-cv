"""Piezas compartidas por los módulos de `cvtitan.commands` (evita importar `cli` y crear ciclos)."""
from __future__ import annotations


class CliError(Exception):
    """Error esperado de un comando: `main()` lo imprime como `Error: ...` y devuelve el código 2."""
