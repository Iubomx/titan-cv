# Cómo agregar una fuente de ofertas (conector)

Las fuentes de la Línea B se registran en `cvtitan/sources.py`. Hay dos formas de agregar una.

## 1. Como plugin (recomendado: no toca el núcleo)

Crea un paquete con una función que recibe un `SourceContext` y devuelve una lista de ofertas:

```python
# mi_paquete/fuentes.py
import json

from cvtitan.apply import intl_sources

def fetch(ctx):                     # ctx.cache: carpeta de caché diaria; ctx.line: config de la línea
    data = intl_sources._cached(ctx.cache, "mi-portal",
                                lambda: json.loads(intl_sources._get("https://example.com/api/jobs")))
    return [{
        "source": "Mi portal", "url": j["url"], "title": j["title"], "company": j["company"],
        "text": j["description"], "regions": ["Worldwide"], "salary": {},
    } for j in data]
```

Decláralo como entry point en el `pyproject.toml` de tu paquete:

```toml
[project.entry-points."cvtitan.sources"]
mi_portal = "mi_paquete.fuentes:fetch"
```

Instala tu paquete en el mismo entorno (`pip install -e .`) y actívalo en `config/lines.yaml`:

```yaml
lines:
  B:
    sources: [remotive, mi_portal]
```

Reglas: una fuente de plugin nunca reemplaza a una integrada; un plugin roto se ignora con un aviso. Respeta los
términos de cada portal, usa la caché (una consulta diaria por fuente) y un User-Agent identificado.

## 2. Integrada en el repositorio

Agrega el *fetcher* en `cvtitan/apply/intl_sources.py` y regístralo en `FETCHERS`; `cvtitan/sources.py` lo expone
automáticamente. Incluye pruebas con respuestas simuladas (sin red) en `tests/`.

## Agregar un país (mercado)

Un `Market` (`cvtitan/markets.py`) define país, términos de la región local (`home_regex`), moneda supuesta para
montos sin moneda, fuentes locales y `Accept-Language`. Publícalo como entry point:

```toml
[project.entry-points."cvtitan.markets"]
peru = "mi_paquete.mercados:PERU"      # un objeto `Market`
```

y actívalo con `lines.A.market: peru` en `config/lines.yaml`. El mercado `chile` es integrado y no se reemplaza.

## Portales locales (Línea A)

Los portales de empleo de tu país viven en `cvtitan/local_sources.py`. Una `LocalSource` construye la URL de búsqueda
y declara los dominios que se leen sin navegador:

```python
from cvtitan.local_sources import LocalSource

TRABAJO_PE = LocalSource("trabajo_pe", lambda kw, loc: f"https://pe.example.com/jobs?q={kw}&city={loc}",
                         frozenset({"pe.example.com"}))
```

```toml
[project.entry-points."cvtitan.local_sources"]
trabajo_pe = "mi_paquete.portales:TRABAJO_PE"
```

Actívala con el `Market` de tu país (`local_sources=(..., "trabajo_pe")`) o en `config/search_keywords.yaml`. Los
portales integrados (Chile) no se pueden reemplazar.

## Siguiente paso previsto

El mismo patrón se extenderá a los portales de postulación (`apply/platforms.py`) y a las URL de búsqueda locales
(`apply/platforms.py`, para postular), que siguen siendo específicos de Chile.
