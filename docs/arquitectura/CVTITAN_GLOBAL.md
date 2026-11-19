# CVTitan Global — arquitectura propuesta y estado

Fecha: 2026-11-17. Estado: **Etapa 1 (registro global antiduplicados) implementada y probada.** El resto es propuesta.
Envíos reales nuevos: **desactivados**. La Línea B tiene `send_enabled: false`; la Línea A mantiene su autorización previa.

## 1. Inspección del sistema actual (resumen)

| Componente | Archivo | Rol en la arquitectura global |
|---|---|---|
| Lectura y análisis de vacantes | `job_intel.py`, `evidence.py`, `taxonomy.py` | QUALIFICATION (sin cambios) |
| Fuentes Chile (HTTP y navegador) | `apply/search.py` | Conectores de DISCOVERY (Línea A) |
| Fuentes internacionales (APIs y feeds) | `apply/intl_sources.py` | Conectores de DISCOVERY (Línea B) |
| Robot de formularios | `apply/runner.py`, `forms.py`, `answers.py`, `legal.py` | APPLICATION |
| Historial y CV | `db.py` (tabla `applications`) | Detalle por postulación (CV, capturas, eventos) |
| **Registro global (nuevo)** | `registry.py` (tablas `employers`, `vacancies`, `vacancy_sources`, `attempts`) | Identidad, estado e idempotencia de cada vacante |

## 2. Arquitectura objetivo

```
                    ┌──────────── PLANIFICADOR (cada N horas, retoma donde quedó) ────────────┐
                    │  geo_catalog: Continente → País → Región → Ciudad (+ fecha de exploración)│
                    └───────────────┬───────────────────────────────────────────────────────┘
          DISCOVERY (conectores independientes, límites por dominio, backoff, circuit breaker)
     Get on Board · Chiletrabajos · portales de empresas · Remotive · RemoteOK · Himalayas · Jobicy · WWR ·
     Arbeitnow · Greenhouse/Lever/Ashby/SmartRecruiters por empresa · LinkedIn (con sesión) · …
                    │  register() → vacancies (DISCOVERED) + vacancy_sources (cada URL)
          QUALIFICATION (solo CPU local; no depende de portales)
     elegibilidad (región oficial + texto, «gana lo estricto») · filtros legales · puntaje · sueldo
                    │  QUALIFIED / CLOSED (con motivo)
          APPLICATION (solo con autorización, por línea)
     claim() atómico → formulario → mark_clicked() → «Enviar» → finish(confirmed | unknown | failed …)
                    │
          OBSERVABILIDAD: panel local (países y ciudades exploradas, embudo, conversión, fallos por portal)
```

Las tres etapas son **independientes**: si un portal de postulación está bloqueado o requiere a la persona, la
búsqueda y la calificación siguen. El registro persiste en SQLite (modo WAL) y las consultas son SQL estándar,
preparadas para migrar a PostgreSQL.

## 3. Etapa 1 — registro global antiduplicados (implementado)

**Identidad lógica (`logical_key`):**
1. ID del ATS o de la bolsa: Greenhouse, Lever, Ashby, Workday, SmartRecruiters, SuccessFactors, Get on Board,
   Computrabajo y Chiletrabajos. Los IDs de LinkedIn e Indeed se guardan solo como URL, porque son de la publicación,
   no de la requisición.
2. Requisición publicada («Req ID», «Job ID», «Código de oferta») + empleador normalizado.
3. Huella secundaria: empleador normalizado + cargo normalizado + lugar (o «remoto»).

**Reglas implementadas:**

| Regla del pedido | Implementación |
|---|---|
| Nunca reenviar `SUBMITTED_CONFIRMED` | `can_submit()` lo bloquea, incluso desde otra URL o portal y tras un reinicio |
| `SUBMISSION_UNKNOWN`: verificar antes de reintentar | Si hubo clic en «Enviar» (`mark_clicked`) y luego un fallo → desconocido → bloqueado |
| `PENDING_REVIEW`: esperar | Bloqueado para envío automático |
| `FAILED`: reintentar solo sin evidencia de envío | Fallo antes del clic → `FAILED` (reintenta); después del clic → `SUBMISSION_UNKNOWN` |
| Nueva requisición = vacante distinta | Distinto ID de ATS o de requisición → otra vacante, aunque el cargo sea idéntico |
| No asumir igualdad por cargo y empresa | La huella incluye el lugar; con IDs oficiales distintos nunca se fusionan |
| Persistencia ante reinicios | SQLite + `recover_stale()` (bloqueos vencidos tras una caída) |
| Concurrencia | `claim()` = `UPDATE … WHERE status IN (…)` atómico; solo un worker gana |
| Importar el historial | `cvtitan registro importar` (idempotente): 30 registros → **26 vacantes**; **13 confirmadas** |

**Integración:**
- `BatchApplier`, usado por `postular` y `auto`, consulta el registro antes de procesar, reclama antes de enviar,
  marca el clic y registra el resultado.
- La Línea B registra cada vacante descubierta y su calificación.

**Pruebas obligatorias** (`tests/test_registry.py`, ninguna envía nada):

| # | Escenario | Estado |
|---|---|---|
| 1 | Reinicio del agente sin duplicar envíos | ✅ `test_1_restart_never_resubmits` |
| 2 | Misma vacante en cinco portales | ✅ `test_2_same_vacancy_in_five_portals` (una sola vacante, 5 URLs) |
| 3 | Dos workers con la misma vacante | ✅ `test_3_two_workers_same_vacancy` (con hilos simultáneos) |
| 4 | Falla de conexión después de pulsar enviar | ✅ `test_4_failure_after_pressing_submit` |
| 5 | Requisición nueva con cargo idéntico | ✅ `test_5_new_requisition_same_title_is_distinct` |
| 6 | Sesión caducada | ⚠️ Cubierto por el flujo existente (pausa de login y ventana de Chrome normal); falta una prueba dedicada |
| 7 | Portal no disponible | ⚠️ La Línea B continúa si una fuente falla (verificado en ejecución real con Jobicy y WWR); falta prueba unitaria |
| 8 | Respuestas legales desconocidas | ✅ `test_legal_guard_never_declares_false_facts` (quedan pendientes) |
| 9 | Falta de API de IA | ✅ `test_llm_disabled_by_default` + todo el sistema corre sin IA |
| 10 | Recuperación de registros históricos | ✅ `test_10_import_history` + importación real |
| — | Proceso caído con bloqueo tomado | ✅ `test_7_stale_lock_recovered_after_crash` |

Total del proyecto: **44 pruebas aprobadas**.

## 4. Próximas etapas (propuesta, requieren aprobación)

| Etapa | Contenido | Dependencias |
|---|---|---|
| 2. Catálogo geográfico | Tablas `geo_*` cargadas desde **GeoNames** (`countryInfo.txt`, `admin1CodesASCII.txt`, `cities15000.txt`, licencia CC BY 4.0) con IDs estables; tabla `exploration(source, geo_id, query, last_run, results, next_run)`. Primero búsquedas nacionales o regionales; ciudad por ciudad solo si el portal lo requiere y la búsqueda nacional devuelve menos | Ninguna en Python (descarga de archivos públicos) |
| 3. Cola y workers | Tabla `tasks(kind, payload, status, attempts, next_at)`; workers por etapa con `concurrent.futures`; límite por dominio (token bucket), backoff exponencial, circuit breaker por fuente, reanudación | Biblioteca estándar |
| 4. Registro de empleadores | Tabla `employers` + `employer_boards` (ATS detectado: Greenhouse, Lever, Ashby, Workday, SmartRecruiters), descubiertos desde los enlaces «apply» de las fuentes | Biblioteca estándar |
| 5. Puntaje completo | Idioma, beneficios, crecimiento, complejidad de postulación y turnos 7x7 | — |
| 6. Panel | Sección en la web local (FastAPI ya instalado): cobertura geográfica, embudo, duplicados, fallos por portal, conversión por fuente y país, costo de IA | — |
| 7. Categoría «presencial con patrocinio» | Separada de la Línea B; requiere aprobación humana por vacante | — |

**Sobre el volumen:** el sistema no tendrá un tope arbitrario. El volumen real lo limitan las vacantes
**elegibles** desde tu país (abiertas, ambiguas o excluidas según la región publicada) y los
límites que cada portal tolera sin bloquear la cuenta. Los topes por portal (`daily_limits`) se mantienen como
protección contra bloqueos, no como meta.

## 5. Operación

```powershell
.\.venv\Scripts\python.exe -m cvtitan registro                 # estado del registro global
.\.venv\Scripts\python.exe -m cvtitan registro importar        # importar historial (idempotente)
.\.venv\Scripts\python.exe -m cvtitan registro recuperar       # liberar bloqueos de procesos caídos
```
