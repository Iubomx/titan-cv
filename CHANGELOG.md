# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado [SemVer](https://semver.org/lang/es/).

## [Unreleased]

### Added
- i18n: `cvtitan/i18n.py` + `cvtitan/messages.py`, `--lang es|en` y `CVTITAN_LANG`; migrados los mensajes de `validate` (ver `docs/i18n.md`). El español sigue siendo el valor por defecto.
- Mercados por país (`cvtitan/markets.py`, entry points `cvtitan.markets`, `lines.A.market`): moneda supuesta, región local, fuentes y etiquetas ya no están cableadas a Chile.
- `Dockerfile` y `.dockerignore` (análisis sin navegador; datos montados en `/workspace`), job `docker` en CI.
- Registro de fuentes `cvtitan/sources.py` con plugins por entry point `cvtitan.sources`; guía `docs/agregar-conector.md`. `line_b.collect_offers` ya no cablea Greenhouse/Lever.
- `titan purge` (`--outputs`, `--sesiones`, `--historial`, `--cache`, `--todo`): borra lo generado en `data/` con confirmación; nunca toca `candidate/` ni `.env`.
- CI: cobertura mínima (58%), job `typecheck` (mypy, informativo) y workflow de release por tag `v*`.
- Job `audit` en CI (pip-audit, informativo).
- Pruebas para el puntaje de la Línea B y la normalización de sueldos.
- Archivos de comunidad: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, plantillas de issues y PR.
- `README.en.md` (resumen en inglés), `.editorconfig`, `.gitattributes`, Dependabot.
- Lint con Ruff y reporte de cobertura en CI; CI en Python 3.10 a 3.13.
- Extra opcional `ai` (`pip install -e ".[ai]"`) para las funciones de IA.

### Changed
- Portabilidad: `release_profile` y `release_orphans` usan `psutil` (macOS/Linux); `find_chrome` busca Chromium; prioridad baja con `os.nice`; `titan.sh` y guía de tareas programadas (cron/launchd). CI incluye macOS.
- `anthropic` pasa a dependencia opcional; `pydantic` se declara explícitamente.
- Metadatos de empaquetado (licencia, clasificadores, URLs).

### Fixed
- Escape de rutas con apóstrofes o comodines en los comandos de PowerShell de `human_browser.py`.
- `programar_tarea.ps1` advierte si `send_enabled: true`.

## [0.1.0]
- Primera versión pública.
