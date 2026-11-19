# Política compartida de agentes — CV TITAN AI

Este documento vale igual para Claude Code (`CLAUDE.md`) y Codex (`AGENTS.md`).
Ambos agentes trabajan sobre **la misma fuente de verdad** y respetan **las mismas reglas**.

## Principio rector

Cada candidatura debe ser la versión más relevante, precisa y **defendible en entrevista** de la
experiencia real del candidato. Si no se puede respaldar, no entra al CV.

## Fuente de verdad

- `candidate/profile.yaml` es el único perfil del candidato. No mantengas perfiles paralelos,
  ni resúmenes "mejorados" fuera de este archivo.
- Cada logro tiene un `id`. Cada skill tiene un `status`:
  - `backed`: tiene `evidence` que apunta a ids existentes (logros, proyectos completados, estudios, certificaciones).
  - `to_demonstrate`: en aprendizaje o sin prueba. **Nunca** aparece en el CV.
- Solo el candidato puede autorizar cambios en `profile.yaml`. El agente puede proponerlos, pero
  debe preguntar antes de escribirlos, y nunca puede subir una skill a `backed` sin una evidencia concreta
  que el candidato confirme.

## Reglas de integridad (no negociables)

1. **No inventar**: ni tecnologías, ni cifras, ni cargos, ni fechas, ni responsabilidades.
2. **Trazabilidad**: cada bloque de `cv_draft.yaml` (resumen, bullet, proyecto) conserva su `source`.
   Reescribir sí, sustituir el hecho no.
3. **Cifras**: un bullet solo puede contener números que estén en el texto de su fuente.
4. **Skills**: solo skills `backed`. Una brecha se trabaja en la guía de entrevista, no en el CV.
5. **La auditoría manda**: un CV con `audit.md` en estado BLOQUEADO no se entrega.
6. **Honestidad ante brechas**: se reconoce el nivel real, se conecta con una habilidad adyacente
   y se propone un plan concreto.
7. **Privacidad**: los datos del candidato no se envían a servicios externos salvo para descargar
   la vacante que el usuario indicó.

## Los cuatro agentes

| # | Agente | Implementación determinista | Aporte del LLM |
|---|---|---|---|
| 01 | Job Intelligence | `cvtitan analyze` → `data/jobs/<id>/job.yaml` | Revisar la clasificación (obligatorio/deseable), señalar requisitos implícitos y la cultura de la empresa |
| 02 | Candidate Evidence | `cvtitan match` → `match.yaml/.md` | Detectar evidencia implícita y **preguntar** al candidato si es real |
| 03 | CV Optimization | `cvtitan generate` → `cv_draft.yaml`, `cv.docx` | Reescribir bullets y resumen en `cv_draft.yaml` para usar el lenguaje de la vacante sin alterar los hechos |
| 04 | Recruiter Simulation | `cvtitan render` / `audit` → `audit.md` | Hacer una lectura crítica de 6 segundos y luego de 2 minutos; proponer mejoras |

## Flujo estándar de una candidatura

```powershell
cvtitan validate                                   # perfil sin errores
cvtitan analyze --url <URL>  # o --file oferta.txt  (LinkedIn: pega el texto en un archivo)
cvtitan match <job_id>                             # leer match.md con el candidato
cvtitan approve <job_id>                           # solo si el candidato decide postular
cvtitan generate <job_id> [--pdf]
#   el agente mejora cv_draft.yaml (solo redacción) ->
cvtitan render <job_id>                            # repetir hasta APROBADO
cvtitan interview <job_id>
cvtitan track add <job_id> --status applied
```

Atajo sin revisión intermedia: `cvtitan run --file oferta.txt --company "X"`.

## Cómo editar `cv_draft.yaml`

Permitido:
- Reordenar bullets y secciones.
- Reformular con verbo de acción + qué + resultado, usando la terminología de la vacante
  (p. ej., "reportabilidad" → "automatización de reportes operacionales"), siempre que el hecho sea el mismo.
- Elegir otro resumen de `summary_variants` o acortarlo.
- Quitar bullets poco relevantes.

Prohibido:
- Cambiar o quitar el `source` de un bloque, o crear bloques sin `source`.
- Agregar números, porcentajes, montos, plazos o tamaños de equipo que no estén en la fuente.
- Mencionar tecnologías no respaldadas, aunque la vacante las pida.
- Editar `skills` para añadir algo que no sea `backed`.

Después de cada edición: `cvtitan render <job_id>` y leer `audit.md`.

## Simulación de reclutador (lectura del LLM)

Además de la auditoría automática, responde por escrito en `data/outputs/<job_id>/review.md`:
1. Lectura de 6 segundos: ¿qué cargo, seniority y especialidad transmite la parte superior?
2. ¿Los 3 requisitos más importantes aparecen en el primer tercio del CV?
3. ¿Qué afirmación pediría probar un reclutador escéptico? ¿Existe esa evidencia?
4. Las 3 debilidades principales y cómo mitigarlas sin inventar.

## Postulación automática (web local)

`cvtitan web` (o doble clic en `CV TITAN.bat`) abre `http://127.0.0.1:8765`. Al pegar un link:

1. El robot (Playwright + Chrome con perfil propio en `data/browser-profile`) abre la vacante y la lee.
2. Claude extrae país, ciudad, modalidad, salario y requisitos; luego vienen el matching y el CV adaptado.
   Cada reescritura de la IA pasa la auditoría bloque por bloque y, si falla, vuelve al texto original.
3. Completa el formulario con el perfil, `preferences`, `documents` y `candidate/answers.yaml`.
   Lo que no está en esas fuentes **se pregunta** en la web (estado «Necesita tu respuesta») y se recuerda.
4. Se detiene en «Listo para revisar» con una captura de pantalla. **Solo envía cuando el candidato pulsa
   «Enviar postulación».** CAPTCHA y login siempre los resuelve el candidato en la ventana de Chrome.
5. El historial (`data/cvtitan.db`) guarda la fecha, empresa, cargo, país, modalidad, salario, ajuste,
   brechas, estado del proceso, notas y eventos.

Desde la terminal, sin la web (comparten navegador, así que no corras ambas a la vez):

```powershell
cvtitan postular https://www.getonbrd.com/jobs-postgres          # listado: recorre todas sus vacantes
cvtitan postular --linkedin "python developer" --linkedin "power bi" --lugar Chile --max 10
```

Pregunta en la terminal lo que no sabe, muestra lo completado y envía solo si respondes «s».

Reglas adicionales del robot:
- No evadir CAPTCHA ni detección de bots; no crear cuentas por el candidato.
- Respetar `daily_limits` de `config/settings.yaml` (LinkedIn prohíbe la automatización: límite bajo y ritmo lento).
- Respuestas legales o demográficas (visa, género, discapacidad): solo desde preferencias o «prefiero no responder».

## Aprendizaje

`cvtitan track update <job_id> --status screening|interview|rejected|...` y `cvtitan track stats`.
Con 10 o más candidaturas, compara el score de las que avanzan con el de las que no, y ajusta qué vacantes priorizar.
