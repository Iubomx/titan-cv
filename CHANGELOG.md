# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado [SemVer](https://semver.org/lang/es/).

## [Unreleased]

## [0.1.0] - 2026-11-20

Primera versión etiquetada. Reúne la publicación inicial y todo lo siguiente: seguridad (envío con revisión humana,
IA con datos minimizados, cifrado en reposo, web protegida), calidad (CI, tipado, cobertura, macOS, Docker),
extensibilidad (plugins de fuentes, mercados y portales) y mejoras de producto.

### Security
- **Web local protegida contra CSRF y DNS rebinding** (`web/guard.py`): las acciones que modifican datos exigen un token por ejecución (solo se entrega en la página principal) y se rechazan `Host` y `Origin` que no sean localhost. Antes cualquier página abierta en el navegador podía llamar a `127.0.0.1:8765`.
- **La IA recibía nombre, correo, teléfono y ciudad.** El bloque `personal` viajaba completo a la API en las respuestas de formularios y las cartas. Ahora se minimiza por defecto (ver Added) y cada solicitud queda registrada localmente. **Cambio de comportamiento:** las respuestas redactadas por la IA ya no pueden usar esos datos; si faltan, la pregunta queda pendiente para ti.
- **La Línea A no respetaba `send_enabled`.** Solo la Línea B comprobaba ese ajuste; `titan auto` (modo `apply`) podía enviar postulaciones de la Línea A aunque `lines.A.send_enabled` fuera `false`, contra lo documentado. Ahora ambas líneas pasan por `send_policy.decide`: solo `send_enabled: true` (booleano exacto) permite enviar.
- **Revisión humana por defecto.** Nuevo `lines.<A|B>.review_mode` (`always` por defecto): el autopilot deja cada formulario listo en «awaiting_review» y el envío lo apruebas tú (web o `postular --pendientes --ver`). `review_mode: auto` conserva el envío sin confirmación para quien lo elija explícitamente. **Cambio de comportamiento:** quien tenía `send_enabled: true` y dependía del envío automático debe agregar `review_mode: auto`.

### Added
- Portales locales en un registro con plugins (`local_sources.py`, entry point `cvtitan.local_sources`): `source_url` y los dominios sin navegador ya no están cableados en `search.py`. Las URL integradas no cambian.
- Tipado: el job `typecheck` de mypy (bloqueante) pasa de 12 a 33 módulos (`colors`, `report` y `cv_writer` quedan pendientes: requieren tipos de `rich` y `python-docx`); se corrigieron 6 observaciones menores (`geo`, `privacy`, `job_intel`, `market`).
- Refactor (parte 3): `web`, `postular`, `showcase`, `demo`, `buscar` y `sesiones` pasan a `cvtitan/commands/robot.py`; `RobotLock` a `commands/_robot.py`. `cli.py` queda en unas 325 líneas (solo `auto` y el arranque). Nueva prueba estática que verifica que todos los imports relativos de `commands/` resuelven, y que cada comando responde a `--help`.
- Cifrado en reposo con passphrase: `titan vault lock|unlock|status` (`vault.py`, extra opcional `[vault]`). Cifra `candidate/*.yaml`, documentos, `.env`, la base de datos y los CV generados en un solo archivo `vault.titanvault`; verifica todo antes de borrar los originales y no escribe nada si la passphrase es incorrecta. El escaneo del CI prohíbe subir `*.titanvault`.
- `titan informe --semana [--dias N]`: informe semanal con envíos por día, tasa de respuesta, mediana de días hasta la primera respuesta, empresas con más postulaciones y agenda (`weekly.py`). Solo datos reales; sin URLs.
- CRM de postulaciones: hitos del proceso (tabla `process_events`) con `titan track event <job_id> --kind interview|followup|test|offer|other --on AAAA-MM-DD`, `titan track agenda [--days N]` (incluye atrasados) y `titan track done <id>`.
- Refactor (parte 2): `publish`, `informe`, `geo`, `registro` y `mercado` pasan a `cvtitan/commands/reports.py`; pruebas de humo para los comandos movidos (`tests/test_cli_smoke.py`).
- Refactor: el flujo de CV (`validate`, `import-cv`, `analyze`, `match`, `approve`, `generate`, `render`, `audit`, `interview`, `run`, `jobs`, `track`) pasa a `cvtitan/commands/pipeline.py` y los helpers a `commands/_common.py`; `cli.py` baja de 1092 a unas 790 líneas. Sin cambios de comportamiento.
- Explicabilidad del puntaje de la Línea B: el desglose (compatibilidad, elegibilidad, sueldo, experiencia) se guarda por oferta en `*-decisiones.csv` y `*-funnel.csv`; `line_b.explain_score` calcula el aporte de cada componente. El embudo conserva los ceros (antes un puntaje 0 salía vacío).
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

## Historial anterior
- Primera versión pública (publicación inicial del repositorio, sin etiqueta).
