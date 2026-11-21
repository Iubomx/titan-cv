"""Comprueba un portal de empleo ANTES de agregarlo a config/job_boards.yaml.

    python scripts/probe_board.py "https://www.reed.co.uk/jobs/{slug}-jobs" --keyword "data analyst"

Descarga la página de búsqueda como lo haría `cvtitan buscar` (sin navegador) y muestra:
  - el código HTTP y el tamaño (403 = bloquea clientes automáticos; HTML casi vacío = se carga con JavaScript);
  - las formas de enlace más frecuentes (de ahí sale la expresión `job_link` de UNA oferta);
  - con --job-link, cuántos enlaces de oferta reconoce y si el lector entiende la primera página de oferta.
Solo agrega el portal si hay ofertas en el HTML y el lector extrae el título. Respeta sus términos de uso.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from cvtitan import job_intel, local_sources  # noqa: E402
from cvtitan.net import fetch  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


def shape(path: str) -> str:
    path = re.sub(r"[0-9a-f]{8,}", "<hex>", path)
    path = re.sub(r"\d+", "<n>", path)
    return re.sub(r"[a-z0-9]+(?:-[a-z0-9]+){2,}", "<slug>", path)


def get(url: str) -> tuple[str, str]:
    raw, charset = fetch(url, {"User-Agent": UA, "Accept-Language": "es,en;q=0.8"}, 20)
    return raw.decode(charset or "utf-8", errors="replace"), url


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("template", help="Plantilla de búsqueda con {keyword} o {slug} (y opcionalmente {location}).")
    ap.add_argument("--keyword", default="data analyst")
    ap.add_argument("--location", default="")
    ap.add_argument("--job-link", help="Expresión regular de un enlace de oferta, para comprobarla.")
    args = ap.parse_args()

    url = local_sources.render_url(args.template, args.keyword, args.location)
    print(f"Búsqueda: {url}")
    try:
        body, final = get(url)
    except Exception as exc:
        print(f"No se pudo leer ({type(exc).__name__}). Probablemente bloquea clientes automáticos: no apto sin navegador.")
        return 1
    print(f"Descargado: {len(body) // 1024} KB")
    host = urlparse(final).netloc
    hrefs = [urljoin(final, h) for h in re.findall(r'href="([^"#]+)"', body)]
    shapes = Counter(urlparse(h).path and shape(urlparse(h).path) for h in hrefs if urlparse(h).netloc == host)
    print("Formas de enlace más frecuentes del mismo dominio (candidatas a job_link):")
    for form, n in shapes.most_common(6):
        print(f"  {n:4}  {form}")
    if len(body) < 80_000 and len(hrefs) < 20:
        print("AVISO: HTML casi vacío: el listado probablemente se carga con JavaScript (no sirve con http: true).")
    if not args.job_link:
        return 0
    rx = re.compile(args.job_link)
    links = list(dict.fromkeys(u.split("?")[0] for u in hrefs if rx.search(u.split("?")[0])))
    print(f"\njob_link reconoce {len(links)} enlaces de oferta.")
    if links:
        try:
            raw = job_intel.parse_html(get(links[0])[0])
            print(f"Primera oferta: {links[0]}\n  título: {raw.get('title')!r}  empresa: {raw.get('company')!r}  "
                  f"texto: {len(raw.get('text') or '')} caracteres")
        except Exception as exc:
            print(f"No se pudo leer la oferta ({type(exc).__name__}).")
    return 0 if links else 2


if __name__ == "__main__":
    raise SystemExit(main())
