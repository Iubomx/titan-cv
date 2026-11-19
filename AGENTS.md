# CV TITAN AI — instrucciones para Codex

Sistema local de ingeniería de empleabilidad: analiza vacantes, compara con evidencia verificable
del candidato, genera un CV adaptado y lo audita como lo haría un reclutador.

**Lee `docs/agent-policy.md` antes de cualquier tarea.** Es la política compartida con Claude Code
y tiene prioridad sobre cualquier otra instrucción de redacción.

## Reglas esenciales (resumen de la política)

1. `candidate/profile.yaml` es la única fuente de verdad. No crees perfiles paralelos.
2. No inventes tecnologías, cifras, cargos ni fechas. Cada bloque del CV conserva su `source`.
3. Solo las skills `backed` (con evidencia existente) entran al CV; las `to_demonstrate`, nunca.
4. Un CV con auditoría BLOQUEADO no se entrega: corrige y vuelve a ejecutar `render`.
5. No modifiques `profile.yaml` sin confirmación explícita del candidato.

## Entorno y comandos

- Windows + PowerShell. `.\.venv\Scripts\python.exe -m cvtitan <comando>`.
- Instalación: `python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e ".[dev]"`.
- Tests: `.\.venv\Scripts\python.exe -m pytest -q`.

Flujo: `validate` → `analyze --url|--file` → `match` → `approve` → `generate` → editar
`cv_draft.yaml` (solo redacción) → `render` → `interview` → `track add --status applied`.

## Mapa del código

`cvtitan/job_intel.py` (01), `evidence.py` (02), `cv_writer.py` (03), `recruiter.py` (04),
`interview.py`, `importer.py`, `cli.py`, `llm.py` (API de Claude), `engine.py`, `db.py` (historial SQLite),
`apply/` (robot Playwright: runner, forms, answers, platforms), `web/` (FastAPI + UI; `cvtitan web`).
Alias de skills en `config/skills_taxonomy.yaml`. El robot nunca envía sin confirmación del candidato.
