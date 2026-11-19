---
description: Analiza una vacante y prepara una candidatura completa basada en evidencia
argument-hint: <url de la vacante o ruta a un .txt con la descripción>
---

Prepara una candidatura para: $ARGUMENTS

Sigue `docs/agent-policy.md` al pie de la letra.

1. Ejecuta `.\.venv\Scripts\python.exe -m cvtitan validate`. Si hay errores, detente y explícalos.
2. Analiza la vacante con `cvtitan analyze` (usa `--url` si es una URL o `--file` si es un archivo; si es LinkedIn y falla,
   pide al usuario que pegue el texto). Lee `job.md` y corrige mentalmente clasificaciones dudosas.
3. Ejecuta `cvtitan match <job_id>` y muestra al usuario: score, cobertura de obligatorios, años,
   brechas y evidencia implícita. Si hay evidencia implícita, pregunta si es real antes de tocar el perfil.
4. Pregunta si quiere postular. Si responde que sí: `cvtitan approve <job_id>` y luego `cvtitan generate <job_id>`.
5. Mejora `data/outputs/<job_id>/cv_draft.yaml` solo en redacción: verbos de acción, terminología de la vacante
   y requisitos clave arriba. Conserva cada `source` y no agregues cifras ni tecnologías.
6. Ejecuta `cvtitan render <job_id>` hasta que la auditoría quede APROBADA.
7. Escribe `review.md` (simulación de reclutador, sección de la política) y ejecuta `cvtitan interview <job_id>`.
8. Responde con las rutas de `cv.docx`, `audit.md`, `interview.md` y `review.md`, más las 3 brechas principales.
