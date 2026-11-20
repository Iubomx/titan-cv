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

## Siguiente paso previsto

El mismo patrón se extenderá a los portales de postulación (`apply/platforms.py`) y a los mercados por país.
