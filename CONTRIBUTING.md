# Contribuir a TITAN CV

¡Gracias por querer mejorar el proyecto! / Thanks for helping. Issues and PRs are welcome in Spanish or English.

## Antes de empezar

1. Lee `AGENTS.md`: mapa del sistema, comandos e **invariantes** que no se pueden romper.
2. Busca un issue existente o abre uno para proponer el cambio (etiquetas `good first issue` y `help wanted`).

## Entorno

```powershell
git clone https://github.com/<tu-usuario>/titan-cv.git
cd titan-cv
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

Calidad (lo mismo que corre el CI):

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe scripts/public_scan.py
pip install pre-commit; pre-commit install       # opcional: lo ejecuta en cada commit
```

Las funciones de IA son opcionales: `pip install -e ".[ai]"`.

## Reglas del proyecto

- **Cambios pequeños y enfocados**, con pruebas en `tests/` usando datos ficticios.
- **Nunca incluyas datos personales reales** (nombres, correos, teléfonos, RUT, URLs de tu cuenta, sesiones de navegador). Usa `@example.com` y nombres inventados. El CI (`scripts/public_scan.py`) rechaza el PR si detecta datos personales o secretos.
- **No debilites las garantías**: no inventar experiencia ni cifras, envíos solo con `send_enabled: true`, sin evadir CAPTCHA ni anti-bot, respuestas legales solo desde `declarations.yaml`, enmascarado de privacidad.
- Cambios en el envío automático, el guardia legal o `privacy.py` requieren aprobación explícita de un mantenedor.
- Código en inglés; mensajes al usuario en español; `pathlib` y type hints.

## Pull requests

1. Crea una rama desde `main` y haz commits claros.
2. `pytest -q` debe pasar completo.
3. Completa la plantilla del PR (incluye la casilla de datos personales).

## Seguridad

No abras issues públicos por vulnerabilidades: lee `SECURITY.md`.
