"""Portal público de vacantes de 123GO, con fichas JobPosting del empleador."""
from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .. import job_intel
from .intl_sources import _cached, _get

INDEX = "https://equipo123go.com/vacantes/"


def _detail(url: str, mode: str) -> dict | None:
    raw = _get(url, timeout=15, retries=0).decode("utf-8", errors="replace")
    posting = job_intel._jsonld_jobposting(raw)
    if not posting or not posting.get("description") or not posting.get("title"):
        return None
    meta = job_intel.parse_html(raw)
    city, country = meta.get("city"), meta.get("country")
    if not city or not country:
        return None
    if meta.get("modality") == "remoto":
        mode = "remote"
    location = f"{city}, {country}"
    return {
        "source": "123GO", "url": url, "title": posting["title"], "company": meta.get("company") or "123GO",
        "text": meta["text"], "location": location, "workplace_type": mode,
        "regions": [location] if mode == "remote" else None,
        "salary": job_intel._posting_salary(posting), "valid_through": posting.get("validThrough"),
    }


def equipo123go(cache: Path, line: dict) -> list[dict]:
    """Recorre las fichas enlazadas desde el listado vigente; nunca toca formularios."""
    from ..line_b import title_matches

    def listing():
        raw = _get(INDEX, timeout=15, retries=0).decode("utf-8", errors="replace")
        cards = re.findall(r"(?is)<article\b([^>]*\bdata-type=[^>]*)>(.*?)</article>", raw)
        if not cards:
            raise ValueError("123GO: no se reconoció el formato del listado")
        selected = {}
        for attrs, body in cards:
            title = re.search(r"(?is)<h3\b[^>]*>(.*?)</h3>", body)
            link = re.search(r"""(?i)\bhref=["']([^"']+)["']""", body)
            if not title or not link:
                continue
            url = urljoin(INDEX, link[1])
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname != urlparse(INDEX).hostname or url == INDEX:
                continue
            mode = "hybrid" if re.search(r"""(?i)\bdata-type=["'][^"']*\bhibrido\b""", attrs) else "on-site"
            selected[url] = (job_intel._html_to_text(title[1]), mode)
        return selected

    cards = _cached(cache, "equipo123go-indice", listing)
    selected = [(url, mode) for url, (title, mode) in cards.items() if title_matches(title, [], line)]

    def read(item):
        url, mode = item
        key = "equipo123go-" + hashlib.sha256(url.encode()).hexdigest()[:20]
        try:
            return _cached(cache, key, lambda: _detail(url, mode))
        except Exception:
            return None  # Una ficha caída no cancela las demás.

    with ThreadPoolExecutor(max_workers=4) as pool:
        return [offer for offer in pool.map(read, selected) if offer]
