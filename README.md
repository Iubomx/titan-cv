# TITAN CV

**Español** · [English](README.en.md)

Sistema local de **búsqueda y postulación a empleos basado en evidencia**, con un centro de mando en la terminal.
Cada afirmación que llega a un CV o a un formulario sale de un hecho verificable del perfil del candidato:
el sistema **nunca inventa** experiencia, cifras ni respuestas legales.

- 100 % local (Python + Playwright + SQLite). La IA (Claude) es opcional y está desactivada por defecto.
- Este repositorio **no incluye datos de ninguna persona**: trae plantillas ficticias para que configures los tuyos.
- Los envíos automáticos vienen **desactivados**. Lee [Uso responsable](#uso-responsable) antes de activarlos.
- ¿Trabajas con un agente de IA (Codex, Claude Code, Cursor, Copilot...)? Empieza por [`AGENTS.md`](AGENTS.md):
  mapa del sistema, comandos, invariantes y dónde cambiar cada cosa.

```
Descubrir (portales, APIs públicas, ATS de empresas)
  -> Filtrar (cargo, duplicados, registro global)
  -> Evaluar (elegibilidad desde tu país, compatibilidad con evidencia, sueldo, nivel)
  -> Postular (Playwright, solo si lo autorizas)
  -> Informe (embudo de cada oferta, motivos de descarte, métricas)
```

---

## 1. Requisitos

- Windows 10/11 con PowerShell (también funciona en macOS/Linux con ajustes menores de rutas).
- Python 3.10 o superior.
- Google Chrome (recomendado) o Chromium de Playwright.
- Opcional: clave de API de Anthropic para las funciones de IA.

## 2. Instalación

```powershell
git clone https://github.com/Stoneroadd/titan-cv.git
cd titan-cv
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m playwright install chromium      # solo si no usarás Google Chrome
.\.venv\Scripts\python.exe -m pytest -q                        # todo debe pasar antes de empezar
.\.venv\Scripts\python.exe -m pip install -e ".[ai]"            # opcional: funciones de IA (Anthropic)
```

`titan.cmd` es un atajo: `.\titan <comando>` equivale a `.\.venv\Scripts\python.exe -m cvtitan <comando>`.

## 3. Configura TUS datos

Nada de lo que crees en este paso se versiona (ver `.gitignore`). Nunca subas estos archivos a un repositorio.

```powershell
.\titan init                                                            # crea candidate/profile.yaml
Copy-Item candidate\declarations.example.yaml candidate\declarations.yaml
Copy-Item candidate\question_bank.example.yaml candidate\question_bank.yaml
Copy-Item .env.example .env                                             # opcional (clave de Anthropic)
.\titan validate                                                        # revisa tu perfil
```

| Archivo | Qué contiene | Regla clave |
|---|---|---|
| `candidate/profile.yaml` | Datos de contacto, experiencia, logros, proyectos, estudios, certificaciones, skills, preferencias (pretensión, disponibilidad, motivación) y rutas a tus CV (`cv_files`) | Una skill es `backed` solo si `evidence` apunta a ids reales; `to_demonstrate` nunca se afirma |
| `candidate/declarations.yaml` | Ciudadanía, residencia, autorización de trabajo, patrocinio, clearance | Es la **única** fuente para preguntas legales; si falta un dato, la pregunta queda pendiente |
| `candidate/question_bank.yaml` | Respuestas a preguntas frecuentes por patrones (regex) | Solo hechos de tu perfil o decisiones tuyas |
| `candidate/documents/` | Tus CV en PDF (uno por idioma) | Referenciados desde `cv_files` en el perfil |
| `.env` | `ANTHROPIC_API_KEY` | Opcional; actívala además con `llm.enabled: true` en `config/settings.yaml` |

Inicia sesión una sola vez en los portales que lo requieren (se abre Chrome; al cerrarlo, la sesión queda guardada
en `data/browser-profile/`):

```powershell
.\titan sesiones --solo linkedin
```

## 4. Configura la búsqueda

| Archivo | Para qué |
|---|---|
| `config/lines.yaml` | Dos líneas independientes: **A** (portales locales) y **B** (remoto internacional). `send_enabled`, cupo diario, puntaje mínimo, sueldo, fuentes, LinkedIn, escáner de portales ATS |
| `config/auto.yaml` | Reglas de la Línea A: cargos incluidos/excluidos (regex), puntaje mínimo, regla de sueldo, cupo diario, portales que solo admiten postulación manual |
| `config/search_keywords.yaml` | Grupos de palabras clave por portal y el bloque `dictionary` |
| `config/job_dictionary.json` | Catálogo de cargos por categoría y prioridad (P1/P2/P3) |
| `config/companies.yaml` | Portales de empleo de empresas específicas |
| `config/skills_taxonomy.yaml` | Skills, categorías y alias que el sistema reconoce en las vacantes |
| `config/settings.yaml` | Navegador, límites por portal, límites de LinkedIn, IA, interfaz (casco animado, efectos) |

Todos estos archivos son **plantillas** (marcadas `# PLANTILLA`) con un ejemplo de perfil de datos/software y
conectores locales para Chile: reemplaza cargos, palabras clave, empresas y prioridades por los tuyos.
`config/companies.yaml` viene vacío y `send_enabled` / LinkedIn vienen desactivados.

## 5. Uso

```powershell
.\titan auto --modo hunter      # descubre en la Línea A, sin enviar
.\titan auto --modo global      # escáner internacional, sin enviar
.\titan auto --modo analysis    # evalúa ambas líneas, sin enviar
.\titan auto                    # misión completa (envía SOLO si send_enabled: true; con review_mode: always dejas tú la aprobación final)
.\titan auto --modo stealth     # salida de texto simple
.\titan demo <URL>              # mira al robot llenar un formulario (no envía sin --enviar)
.\titan postular --pendientes --ver   # termina lo que requiere a una persona (CAPTCHA, códigos)
.\titan informe                 # último informe de misión
.\titan informe --historial     # historial de postulaciones
.\titan informe --ref JOB-XXXXXXXX   # URL real de un código
.\titan showcase                # centro de mando con datos SIMULADOS (demostración)
```

Cada misión deja en `data/auto/runs/`: registro de eventos, informe y `*-funnel.csv` con el recorrido de cada
oferta (nivel `high/held/manual/potential/review/no` y motivo).

Flujo de CV adaptado paso a paso: `analyze` -> `match` -> `approve` -> `generate` -> `render` -> `interview`
(ver `docs/agent-policy.md`).

## 6. Uso responsable

- **No se evaden CAPTCHA ni sistemas anti-bot**, no se crean cuentas y no se manejan contraseñas: login, CAPTCHA y
  códigos por correo los resuelve una persona.
- Respeta los términos de cada portal. LinkedIn prohíbe la automatización: hay límites estrictos y `--sin-linkedin`.
- Postular en masa y sin criterio perjudica al candidato (los ATS registran a cada postulante). Mantén reglas de
  compatibilidad y un cupo diario razonable.
- Las respuestas legales salen solo de `declarations.yaml`. No conviertas datos inciertos en afirmaciones.

## 7. Privacidad por diseño

- `cvtitan/privacy.py` enmascara en terminal, centro de mando, registros e informes: nombre, correo, teléfono,
  ciudad, LinkedIn, RUT y cualquier correo o teléfono internacional. Las URLs se muestran como
  `dominio #JOB-XXXXXXXX`. Los formularios sí reciben los datos reales.
- La IA nunca recibe archivos, casillas de consentimiento ni preguntas legales.
- `data/`, `candidate/*` (salvo los `.example`), `.env` y las sesiones del navegador están en `.gitignore`.

## 8. Arquitectura

| Módulo | Rol |
|---|---|
| `cvtitan/cli.py` | Comandos, arranque, bloqueo del navegador, informe final |
| `cvtitan/autopilot.py` · `cvtitan/line_b.py` | Línea A (local) y Línea B (remoto internacional) |
| `cvtitan/apply/search.py` · `apply/intl_sources.py` | Búsqueda en portales (HTTP en paralelo + caché) y fuentes/APIs internacionales, escáner ATS |
| `cvtitan/apply/runner.py` · `apply/forms.py` · `apply/batch.py` | Robot Playwright: abrir, llenar, validar, enviar, pausar |
| `cvtitan/apply/answers.py` · `apply/question_bank.py` · `apply/legal.py` | Respuestas: perfil, diccionario, motor de evidencias, guardia legal |
| `cvtitan/registry.py` · `cvtitan/db.py` | Registro global antiduplicados (estados de cada vacante) e historial |
| `cvtitan/funnel.py` · `cvtitan/telemetry.py` | Embudo por oferta, métricas y bus de eventos |
| `cvtitan/ui/` | Centro de mando (Rich), casco animado, tema, monitor de recursos, showcase |
| `cvtitan/privacy.py` · `cvtitan/net.py` | Enmascarado de datos y cliente HTTP compartido |
| `cvtitan/job_intel.py` · `evidence.py` · `cv_writer.py` · `recruiter.py` | Análisis de vacantes, matching con evidencia, CV trazable y auditoría |

## 9. Extender el sistema

- **Nueva fuente de ofertas:** agrega un *fetcher* en `cvtitan/apply/intl_sources.py` (devuelve dicts con
  `source, url, title, company, text, regions, salary`), regístralo en `FETCHERS` y en `config/lines.yaml -> sources`.
- **Nuevo portal para postular:** define textos de éxito / ya postulado / bloqueo en `cvtitan/apply/platforms.py`.
- **Nueva pregunta frecuente:** agrega una entrada en `candidate/question_bank.yaml` (o en el ejemplo, si es genérica).
- **Nueva tecnología:** agrégala con su categoría y alias en `config/skills_taxonomy.yaml`.
- **Nuevos cargos:** amplía `config/job_dictionary.json` o las palabras clave de `config/lines.yaml`.

## 10. Contribuir

Lee [`CONTRIBUTING.md`](CONTRIBUTING.md), [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) y [`SECURITY.md`](SECURITY.md).

1. Crea una rama, haz cambios pequeños y agrega pruebas en `tests/`.
2. `.\.venv\Scripts\python.exe -m pytest -q` debe pasar completo.
3. Nunca incluyas datos personales reales en código, pruebas, ejemplos ni commits: usa datos ficticios
   (`@example.com`, `+56 9 1234 5678`, nombres inventados). Hay una prueba que rechaza caracteres de control en el código.
4. Mantén las garantías: no inventar, no evadir CAPTCHA, envíos solo autorizados.

## Licencia

MIT. Ver `LICENSE`.
