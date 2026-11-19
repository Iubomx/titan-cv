# CV TITAN AI — instrucciones para Claude Code

Sistema local de ingeniería de empleabilidad: analiza vacantes, compara con evidencia verificable
del candidato, genera un CV adaptado y lo audita como lo haría un reclutador.

@docs/agent-policy.md

## Entorno

- Windows + PowerShell. Python en `.venv`: `.\.venv\Scripts\python.exe -m cvtitan <comando>`
  (o `cvtitan` con el venv activado: `.\.venv\Scripts\Activate.ps1`).
- Tests: `.\.venv\Scripts\python.exe -m pytest -q`. Deben pasar antes de dar por terminado un cambio de código.
- Código en `cvtitan/` (identificadores en inglés, mensajes y documentos en español).

## Mapa del código

- `job_intel.py` (01): captura URL/texto, secciones, skills ponderadas, años, seniority, idiomas, modalidad.
- `evidence.py` (02): matriz backed / implicit / to_demonstrate / gap y score.
- `cv_writer.py` (03): `cv_draft.yaml` trazable → DOCX/MD/PDF.
- `recruiter.py` (04): auditoría de integridad, keywords y claridad.
- `interview.py`, `importer.py`, `cli.py`.
- `llm.py`: API de Claude (`claude-opus-5-5`, salidas estructuradas, fallbacks de servidor). Sin clave, todo funciona en modo heurístico.
- `engine.py`: vacante → análisis → matching → CV → historial. `db.py`: historial SQLite (`data/cvtitan.db`).
- `apply/`: robot Playwright (`runner.py`), formularios (`forms.py`), respuestas (`answers.py`), plataformas (`platforms.py`).
- `web/`: FastAPI + `static/index.html` (`cvtitan web`). La prueba e2e del robot está en `tests/test_apply_e2e.py`.
- El robot **nunca envía sin la confirmación del candidato** y nunca evade CAPTCHA; no cambies eso.
- `config/skills_taxonomy.yaml`: alias de skills. Si una tecnología de la vacante no se detecta, agrégala aquí.

## Comportamiento esperado

- Cuando el usuario entregue una vacante, sigue el flujo estándar de la política y muéstrale el
  resumen de `match.md` **antes** de aprobar y generar.
- Cuando aparezca evidencia implícita o una brecha, pregunta al usuario; no completes el perfil por tu cuenta.
- Al terminar, entrega las rutas de `cv.docx`, `audit.md` e `interview.md` y las 3 brechas principales.
- Slash command disponible: `/postular <url o archivo>`.
