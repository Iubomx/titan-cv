# Portales de empleo: cobertura y cómo ampliarla

Los portales viven en un **catálogo de datos**, `config/job_boards.yaml`. Agregar uno no requiere código.

## Qué incluye hoy
| Fuente | Cobertura | Cómo se lee |
|---|---|---|
| **Indeed** | 62 países (`indeed_mx`, `indeed_us`, `indeed_uk`...; Chile es `indeed`) | Chrome del robot: bloquea clientes automáticos (403) y pide verificación humana a menudo |
| **Computrabajo** | 16 países (`computrabajo_co`, `computrabajo_pe`...; Chile es `computrabajo`) | HTTP, sin navegador |
| **LinkedIn** | Global, por ubicación (`linkedin`) | Tu sesión en el Chrome del robot, con límites estrictos (LinkedIn prohíbe la automatización) |
| **elempleo** (Colombia), **Catho** (Brasil), **Reed** (Reino Unido), **Job Bank** (Canadá) | Un país cada uno | HTTP, comprobados contra el sitio real |
| **Get on Board**, **Chiletrabajos**, portales de empresas (SuccessFactors) | Latinoamérica / Chile | HTTP |
| **Línea B (remoto internacional)** | Remotive, RemoteOK, Himalayas, Jobicy, Arbeitnow, WeWorkRemotely y los tableros Greenhouse y Lever de miles de empresas (escáner mundial) | APIs públicas |

## Mercados (`lines.A.market` en `config/lines.yaml`)
`chile` (por defecto), `mexico`, `argentina`, `colombia`, `peru`, `uruguay`, `ecuador`, `espana`, `brasil`, `usa`, `uk`,
`canada`. Cada mercado trae sus portales, su moneda y los términos de su región. `cvtitan buscar` usa los del mercado
activo; con `--en nombre1,nombre2` eliges otros del catálogo (por ejemplo `--en indeed_mx,computrabajo_mx,linkedin`).

## Diccionario de cargos
`config/job_dictionary.json` (el tuyo: TI, datos y minería, 21 categorías) se amplía automáticamente con
`config/job_dictionary_extended.json`: **26 categorías más** en español, inglés y portugués (producto, proyectos,
marketing, ventas, finanzas, RR. HH., logística, ingenierías civil, mecánica, eléctrica e industrial, energía, salud,
educación, legal, administración, turismo, retail, creativos, consultoría, banca y riesgo, agro, sector público, ciencia
de datos y geología/minería). Son 47 categorías y unas 760 denominaciones en total.

Todas las categorías nuevas son **P3**, así que lo que se busca por defecto (P1 y P2) no cambia. Para activarlas pon
`dictionary_priorities: [P1, P2, P3]` en `config/auto.yaml` (Línea A) o en `config/lines.yaml` (Línea B). Si una categoría
ya existe en tu archivo, **gana el tuyo**. Una denominación del diccionario es un término de búsqueda, no prueba de experiencia.

## Lo que NO prometemos
No hay «miles de portales» escritos a mano, y no sería honesto decirlo. La cobertura amplia sale de tres vías: familias
por país (Indeed, Computrabajo), los tableros de empresas que descubre el escáner mundial (Greenhouse y Lever) y **tu
propio catálogo**. Se excluyen a propósito los portales que bloquean todo cliente automático (403) y los que solo
muestran ofertas con JavaScript (Bumeran, Zonajobs, Laborum, Naukri, SimplyHired, Welcome to the Jungle...).

## Agregar un portal
1. Comprueba que sirve: `python scripts/probe_board.py "https://sitio.com/empleos/{slug}" --keyword "data analyst"`.
   Si el HTML trae las ofertas, la salida muestra las formas de enlace más frecuentes; de ahí sale `job_link`.
2. Verifícalo: `python scripts/probe_board.py "<plantilla>" --job-link "<regex>"` debe reconocer decenas de enlaces y
   leer el título de la primera oferta.
3. Agrégalo a **tu** `config/job_boards.yaml` (en tu carpeta de trabajo; no reemplaza a los integrados):
   ```yaml
   boards:
     - name: mi_portal
       url: "https://sitio.com/empleos/{slug}"
       job_link: '^https://sitio\.com/oferta/[a-z0-9-]+/\d+$'
       http: true
       title_clean: ['\s+\|\s+Sitio\.com$']     # opcional: sufijo que se quita del título
   ```
4. Úsalo: `cvtitan buscar "data analyst" --en mi_portal`.

Si lo comprobaste y es útil para más gente, propón la entrada en un PR (con la fecha en `verified`).

## Responsabilidad
Respeta los términos de uso y el `robots.txt` de cada sitio, mantén pocas consultas y no intentes saltarte bloqueos ni
CAPTCHA. El programa no lo hace y no debe hacerse.
