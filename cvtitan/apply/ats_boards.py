"""Tableros de empresas en Workable, Recruitee y SmartRecruiters (APIs públicas, sin clave).

Igual que Greenhouse y Lever: se configura una lista de empresas en `config/lines.yaml -> lines.B` (`workable`,
`recruitee`, `smartrecruiters`) y el escáner mundial suma las que TITAN ya descubrió. Cada fuente devuelve ofertas en el
formato común (`source, url, apply_url, title, company, text, regions, salary, tags, onsite`).

Endpoints (comprobados el 2026-11-21):
  Workable         https://apply.workable.com/api/v1/widget/accounts/<cuenta>?details=true   -> {"jobs": [...]}
  Recruitee        https://<empresa>.recruitee.com/api/offers/                                -> {"offers": [...]}
  SmartRecruiters  https://api.smartrecruiters.com/v1/companies/<id>/postings                 -> {"content": [...]}

Estos sistemas se marcan como «requiere persona» (`human_step_ats`): se descubren y evalúan, pero no se postula solo
hasta validar sus formularios.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from .intl_sources import _cached, _get, _per_token, _text

SR_PAGE = 100                 # máximo por página en la API de SmartRecruiters
SR_MAX_PAGES = 5              # tope por empresa: 500 avisos (algunas tienen miles)
SR_MAX_DETAILS = 40           # avisos con descripción completa por empresa (solo los que pasan el filtro de cargo)
PERIODS = {"month": "mes", "monthly": "mes", "year": "año", "yearly": "año", "annual": "año", "hour": "hora",
           "hourly": "hora"}


def _location(remote: bool, country: str = "", city: str = "", full: str = "") -> str:
    """Texto de ubicación en el formato de Greenhouse: dice «Remote» cuando es remoto (lo usa la elegibilidad)."""
    if remote:
        return f"Remote - {country}" if country else "Remote"
    return full or ", ".join(x for x in (city, country) if x)


def _offer(source: str, ats: str, token: str, url: str, apply_url: str | None, title: str, company: str | None,
           body_html: str, remote: bool, loc: str, salary: dict | None = None) -> dict:
    return {"source": f"{source} ({token})", "ats": ats, "url": url, "apply_url": apply_url or url, "title": title,
            "company": company or token, "text": _text(html.unescape(body_html or "")),
            "regions": [loc] if remote else None, "salary": salary or {}, "tags": [],
            # Portal ATS: sin «remote» en la ubicación oficial, la vacante es presencial en ese lugar.
            "onsite": None if remote else (loc or "location not stated")}


# ---------------------------------------------------------------- Workable
def _workable_one(cache: Path, tok: str) -> list[dict]:
    data = _cached(cache, f"wk-{tok}", lambda t=tok: json.loads(
        _get(f"https://apply.workable.com/api/v1/widget/accounts/{t}?details=true")))
    if not isinstance(data, dict):
        return []
    out = []
    for j in data.get("jobs") or []:
        if not j.get("title") or not j.get("url"):
            continue
        remote = bool(j.get("telecommuting"))
        loc = _location(remote, j.get("country") or "", j.get("city") or "")
        out.append(_offer("Workable", "workable", tok, j["url"], j.get("application_url"), j["title"],
                          data.get("name"), j.get("description") or "", remote, loc))
    return out


def workable(cache: Path, tokens: list[str]) -> list[dict]:
    return _per_token(tokens, lambda tok: _workable_one(cache, tok))


# ---------------------------------------------------------------- Recruitee
def _recruitee_salary(s: dict | None) -> dict:
    s = s or {}
    if s.get("min") is None and s.get("max") is None:
        return {}
    return {"salary_min": s.get("min"), "salary_max": s.get("max"), "salary_currency": s.get("currency"),
            "salary_period": PERIODS.get(str(s.get("period") or "").lower())}


def _recruitee_one(cache: Path, tok: str) -> list[dict]:
    data = _cached(cache, f"rc-{tok}", lambda t=tok: json.loads(_get(f"https://{t}.recruitee.com/api/offers/")))
    if not isinstance(data, dict):
        return []
    out = []
    for o in data.get("offers") or []:
        if o.get("status") not in (None, "published") or not o.get("title") or not o.get("careers_url"):
            continue
        remote = bool(o.get("remote"))
        loc = _location(remote, o.get("country") or "", o.get("city") or "", o.get("location") or "")
        body = (o.get("description") or "") + " " + (o.get("requirements") or "")
        out.append(_offer("Recruitee", "recruitee", tok, o["careers_url"], o.get("careers_apply_url"), o["title"],
                          o.get("company_name"), body, remote, loc, _recruitee_salary(o.get("salary"))))
    return out


def recruitee(cache: Path, tokens: list[str]) -> list[dict]:
    return _per_token(tokens, lambda tok: _recruitee_one(cache, tok))


# ---------------------------------------------------------------- SmartRecruiters
def _sr_body(detail: dict) -> str:
    sections = ((detail.get("jobAd") or {}).get("sections") or {})
    return " ".join((sections.get(k) or {}).get("text") or "" for k in
                    ("companyDescription", "jobDescription", "qualifications", "additionalInformation"))


def _sr_one(cache: Path, tok: str, line: dict) -> list[dict]:
    from ..line_b import title_matches          # importación diferida: line_b importa intl_sources
    postings: list[dict] = []
    for page in range(SR_MAX_PAGES):
        url = f"https://api.smartrecruiters.com/v1/companies/{tok}/postings?limit={SR_PAGE}&offset={page * SR_PAGE}"
        data = _cached(cache, f"sr-{tok}-p{page}", lambda u=url: json.loads(_get(u)))
        content = data.get("content") if isinstance(data, dict) else None
        postings += content or []
        if not content or len(content) < SR_PAGE:
            break
    chosen = [p for p in postings if p.get("name") and p.get("id") and title_matches(p["name"], None, line)]
    chosen = chosen[:SR_MAX_DETAILS]                # la descripción completa solo se baja para cargos de interés

    def detail_of(p: dict) -> dict:
        if not p.get("ref"):
            return {}
        try:
            return _cached(cache, f"sr-{tok}-{p['id']}", lambda u=p["ref"]: json.loads(_get(u))) or {}
        except Exception:
            return {}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        details = list(pool.map(detail_of, chosen))
    out = []
    for p, detail in zip(chosen, details):
        loc_info = p.get("location") or {}
        remote = bool(loc_info.get("remote"))
        country = str(loc_info.get("country") or "").upper()
        loc = _location(remote, country, loc_info.get("city") or "", loc_info.get("fullLocation") or "")
        url = detail.get("postingUrl") or f"https://jobs.smartrecruiters.com/{tok}/{p['id']}"
        out.append(_offer("SmartRecruiters", "smartrecruiters", tok, url, detail.get("applyUrl"), p["name"],
                          (p.get("company") or {}).get("name"), _sr_body(detail), remote, loc))
    return out


def smartrecruiters(cache: Path, tokens: list[str], line: dict | None = None) -> list[dict]:
    line = line or {}
    return _per_token(tokens, lambda tok: _sr_one(cache, tok, line))


# Detección de tableros en URLs ya vistas (escáner mundial): nombre del sistema -> expresión con el token como grupo 1.
BOARD_URL_PATTERNS = {
    "workable": re.compile(r"apply\.workable\.com/([a-z0-9][a-z0-9-]*)/j/"),
    "recruitee": re.compile(r"https?://([a-z0-9][a-z0-9-]*)\.recruitee\.com/o/"),
    "smartrecruiters": re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)/\d+"),
}
