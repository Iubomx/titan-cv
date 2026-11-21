"""Fuentes públicas adicionales para buscar publicaciones recientes."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote, urlencode

from ..utils import normalize
from .intl_sources import _cached, _get, _per_token, _text

WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "onsite": "on-site",
             "fully_remote": "remote", "no_remote": "on-site"}


def ashby(cache: Path, boards: list[str]) -> list[dict]:
    """Lee los avisos publicados y visibles en cada portal oficial de Ashby."""
    def board(name):
        endpoint = "https://api.ashbyhq.com/posting-api/job-board/" + quote(name, safe="")
        payload = _cached(cache, f"ashby-board-{quote(name, safe='')}",
                          lambda: json.loads(_get(endpoint, timeout=15, retries=0)))
        offers = []
        for job in payload.get("jobs", []):
            if not job.get("isListed") or not job.get("jobUrl"):
                continue
            mode = WORKPLACE.get(normalize(job.get("workplaceType")))
            locations = [job.get("location"), *(place.get("location") for place in job.get("secondaryLocations") or [])]
            locations = list(dict.fromkeys(place for place in locations if place))
            offers.append({
                "source": f"Ashby ({name})", "company": name, "url": job["jobUrl"],
                "apply_url": job.get("applyUrl"), "title": job.get("title"),
                "text": _text(job.get("descriptionHtml")) or job.get("descriptionPlain") or "",
                "workplace_type": mode, "location": " | ".join(locations),
                "regions": locations if mode == "remote" else None,
                "posted_at": job.get("publishedAt"), "posted_basis": "Publicada por el portal",
                "tags": [job.get("department") or "", job.get("team") or ""],
            })
        return offers
    return _per_token(boards, board)


def getonboard(cache: Path, queries: list[str]) -> list[dict]:
    """Busca en la API pública de Get on Board y lleva al aviso con su enlace oficial."""
    def search(query):
        seen, offers = set(), []
        for page in (1, 2):
            params = urlencode({"query": query, "page": page, "per_page": 25})
            endpoint = "https://www.getonbrd.com/api/v0/search/jobs?" + params
            key = f"getonboard-search-{quote(query, safe='')}-{page}"
            results = _cached(cache, key, lambda: json.loads(_get(endpoint, timeout=15, retries=0)))
            for job in results.get("data", []):
                item = job.get("attributes") or {}
                url = (job.get("links") or {}).get("public_url")
                if not url or url in seen:
                    continue
                seen.add(url)
                mode = WORKPLACE.get(item.get("remote_modality"))
                countries = [name for name in item.get("countries") or [] if name != "Remote"]
                zone = item.get("remote_zone")
                regions = countries or ([zone] if isinstance(zone, str) and zone else [])
                # En Get on Board, fully_remote indica que se acepta trabajar desde cualquier país,
                # salvo las restricciones que el propio aviso señale.
                if mode == "remote" and not regions:
                    regions = ["Worldwide"]
                company = item.get("company") or {}
                text = "\n".join(_text(item.get(field)) for field in
                                 ("description", "functions", "desirable", "benefits"))
                offers.append({
                    "source": "Get on Board", "title": item.get("title"), "url": url,
                    "company": (company.get("attributes") or {}).get("name", ""),
                    "company_id": (company.get("data") or {}).get("id"),
                    "text": text, "location": " | ".join(countries),
                    "regions": regions if mode == "remote" else None,
                    "workplace_type": mode, "posted_at": item.get("published_at"),
                    "posted_basis": "Publicada por el portal", "tags": [item.get("category_name") or ""],
                })
            if page >= (results.get("meta") or {}).get("total_pages", 1):
                break
        return offers
    return _per_token(queries, search)


def getonboard_company(cache: Path, company_id) -> str:
    if not str(company_id).isdigit():
        return ""
    endpoint = f"https://www.getonbrd.com/api/v0/companies/{company_id}"
    try:
        body = _cached(cache, f"getonboard-company-{company_id}",
                       lambda: json.loads(_get(endpoint, timeout=10, retries=0)))
    except Exception:
        return ""
    return ((body.get("data") or {}).get("attributes") or {}).get("name", "")
