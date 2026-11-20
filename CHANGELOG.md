# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado [SemVer](https://semver.org/lang/es/).

## [Unreleased]

### Security
- **La IA recibía nombre, correo, teléfono y ciudad.** El bloque `personal` viajaba completo a la API en las respuestas de formularios y las cartas. Ahora se minimiza por defecto (ver Added) y cada solicitud queda registrada localmente. **Cambio de comportamiento:** las respuestas redactadas por la IA ya no pueden usar esos datos; si faltan, la pregunta queda pendiente para ti.
- **La Línea A no respetaba `send_enabled`.** Solo la Línea B comprobaba ese ajuste; `titan auto` (modo `apply`) podía enviar postulaciones de la Línea A aunque `lines.A.send_enabled` fuera `false`, contra lo documentado. Ahora ambas líneas pasan por `send_policy.decide`: solo `send_enabled: true` (booleano exacto) permite enviar.
- **Revisión humana por defecto.** Nuevo `lines.<A|B>.review_mode` (`always` por defecto): el autopilot deja cada formulario listo en «awaiting_review» y el envío lo apruebas tú (web o `postular --pendientes --ver`). `review_mode: auto` conserva el envío sin confirmación para quien lo elija explícitamente. **Cambio de comportamiento:** quien tenía `send_enabled: true` y dependía del envío automático debe agregar `review_mode: auto`.

### Added
- Umbrales y puntos del puntaje configurables en `config/scoring.yaml` (`scoring.py`): skills mínimas, factor de experiencia, cortes de recomendación y puntos de elegibilidad y sueldo de la Línea B. Los valores por defecto no cambian el comportamiento.
- Privacidad de la IA (`llm_privacy.py`): nombre, correo, teléfono, ubicación y enlaces ya NO se envían a la API salvo `llm.send_contact: true`; documentos de identidad y fecha de nacimiento (`preferences`) nunca salen. Registro local `data/llm_audit.jsonl` (solo metadatos: fecha, función, modelo, secciones, tokens) y comando `titan llmlog`. `titan purge --historial` lo borra.
- `titan preview <job_id>`: HTML del CV adaptado con panel de revisión (diff palabra a palabra contra el perfil, cifras nuevas y fuentes inexistentes resaltadas; no se imprime). `cv_diff.py`.
- `import-cv` asistido: estructura la experiencia (cargo, empresa, fechas, logros con id) y sugiere evidencia por skill; todo queda como sugerencia, ninguna skill pasa a `backed` (`import_experience.py`).
- `titan init --plantilla <rubro>` (software, comercial, salud; ficticias), `--listar` y `--guiado` (asistente que crea un perfil mínimo válido y `declarations.yaml`). El comando `init` pasa a `cvtitan/commands/`.
- Avisos de calidad del perfil (`profile_checks.py`): correo, fechas inválidas o solapadas, claves desconocidas, logros sin cifras, skills con una sola evidencia. `titan schema` genera el esquema JSON del perfil para el editor.
- i18n: `cvtitan/i18n.py` + `cvtitan/messages.py`, `--lang es|en` y `CVTITAN_LANG`; migrados los mensajes de `validate` (ver `docs/i18n.md`). El español sigue siendo el valor por defecto.
- Mercados por país (`cvtitan/markets.py`, entry points `cvtitan.markets`, `lines.A.market`): moneda supuesta, región local, fuentes y etiquetas ya no están cableadas a Chile.
- `Dockerfile` y `.dockerignore` (análisis sin navegador; datos montados en `/workspace`), job `docker` en CI.
- Registro de fuentes `cvtitan/sources.py` con plugins por entry point `cvtitan.sources`; guía `docs/agregar-conector.md`. `line_b.collect_offers` ya no cablea Greenhouse/Lever.
- `titan purge` (`--outputs`, `--sesiones`, `--historial`, `--cache`, `--todo`): borra lo generado en `data/` con confirmación; nunca toca `candidate/` ni `.env`.
- CI: cobertura mínima (58%), job `typecheck` (mypy, bloqueante sobre los módulos tipados) y workflow de release por tag `v*`.
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
