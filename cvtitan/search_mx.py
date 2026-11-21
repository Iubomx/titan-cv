"""Descubrimiento y evaluación de vacantes para México y el área metropolitana de Monterrey."""
from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from . import evidence, job_intel, line_b, sources
from .profile import Profile
from .utils import PACKAGE_ROOT, Workspace, load_yaml, normalize

CONFIG = Path("config/search_mx.yaml")
COLUMNS = (
    "cargo", "empresa", "areas", "modalidad", "ubicacion_publicada", "score", "obligatorios_%",
    "habilidades_respaldadas", "requisitos_por_validar", "sueldo_publicado", "fuente", "consultada", "url",
)
METRO = re.compile(
    r"\b(monterrey|apodaca|san pedro(?: garza garcia)?|san nicolas(?: de los garza)?|santa catarina|"
    r"general escobedo|escobedo|guadalupe|garcia|juarez|pesqueria|salinas victoria|cienega de flores|"
    r"santiago|el carmen|cadereyta(?: jimenez)?|general zuazua|abasolo|hidalgo)\b"
)
MEXICO = re.compile(r"\b(mexico|mx)\b")
STATE = re.compile(r"\b(nuevo leon|n\.?\s*l\.?)\b")
CAPITAL = re.compile(r"\b(mexico city|ciudad de mexico|cdmx)\b")
OTHER_CITY = re.compile(r"\b(guadalajara|puebla|queretaro|merida|tijuana|toluca)\b")
REMOTE = re.compile(r"\b(remote|remot[oa]|teletrabajo|telecommute)\b")
HYBRID = re.compile(r"\b(hybrid|hibrid[oa])\b")
ONSITE = re.compile(r"\b(on[- ]?site|presencial)\b")
REGION = re.compile(r"\b(latam|latin america|latinoamerica|america latina|worldwide|anywhere|global(?:ly)?)\b")
EXPLICIT_REMOTE = re.compile(
    r"\b(?:(?:fully |100% )?remote (?:in|from|within|across|based in)|(?:work|trabaja) (?:remotely )?from|"
    r"remote\s*[-:()]|remot[oa]\s+(?:en|desde)|teletrabajo en)\s*"
    r"(?:mexico(?! city)|latam|latin america|latinoamerica|america latina|anywhere|worldwide)\b"
)
ANY_MEXICO = re.compile(
    r"\b(?:anywhere|any location|any state|cualquier (?:parte|lugar|estado))\s+(?:in|of|en|de)\s+mexico\b"
)
BLOCKED_REMOTE = re.compile(
    r"\b(?:exclud(?:e[sd]?|ing)|except(?: for)?|excepto|excluye)(?: candidates (?:in|from))?\s+mexico\b|"
    r"\bmexico (?:is )?(?:excluded|not eligible|not supported)\b|"
    r"\b(?:must (?:be )?(?:located|based|reside|live) in|authorized to work in|"
    r"remote only in|this (?:job|role|position) is remote (?:in|from)|solo (?:en|desde))\s+(?:the )?"
    r"(?:u\.s\.|usa|us|united states|canada|uk|united kingdom|eu|europe|brazil|colombia|argentina|"
    r"mexico city|ciudad de mexico|cdmx|guadalajara|puebla|queretaro|merida|tijuana|toluca)(?!\w)|"
    r"\b(?:us|usa|u\.s\.|united states|canada|uk|eu|europe|brazil|colombia|argentina|"
    r"south america|mexico city|cdmx)[- ]only\b"
)
CLOSED = re.compile(
    r"\b(no longer accepting applications|applications closed|this (?:job|position) (?:is closed|has been filled)|"
    r"(?:vacante|oferta) (?:cerrada|cubierta|ya no disponible))\b"
)


def _location(offer: dict) -> tuple[str, str] | None:
    """Devuelve modalidad y evidencia geográfica. Una región desconocida queda fuera."""
    regions = offer.get("regions") or []
    official = str(offer.get("location") or offer.get("onsite") or "")
    place = normalize(official)
    workplace = normalize(offer.get("workplace_type"))
    remote_places = normalize(" | ".join(regions))
    title = normalize(offer.get("title"))
    text = normalize(offer.get("text"))
    is_hybrid = workplace == "hybrid" or bool(HYBRID.search(place))
    is_onsite = workplace in ("on-site", "onsite") or bool(ONSITE.search(place))
    if is_hybrid or is_onsite:
        metro = METRO.search(place)
        if metro and (STATE.search(place) or (metro[0] == "monterrey" and
                                              (place == "monterrey" or MEXICO.search(place)))):
            return ("Híbrido" if is_hybrid else "Presencial"), official
        return None
    if not (regions or workplace == "remote" or REMOTE.search(place) or REMOTE.search(title)
            or EXPLICIT_REMOTE.search(text) or ANY_MEXICO.search(text)):
        return None
    if BLOCKED_REMOTE.search(f"{title} | {place} | {remote_places} | {text}"):
        return None
    explicit = EXPLICIT_REMOTE.search(text) or ANY_MEXICO.search(text)
    region_evidence = remote_places or place
    city_restriction = CAPITAL.search(region_evidence) or CAPITAL.search(title) or OTHER_CITY.search(region_evidence)
    if city_restriction and not ANY_MEXICO.search(text):
        return None
    if region_evidence and not (MEXICO.search(region_evidence) or REGION.search(region_evidence)):
        if not re.fullmatch(r"(?:remote|remot[oa]|location not stated)", region_evidence):
            return None
    if MEXICO.search(region_evidence) or REGION.search(region_evidence):
        return "Remoto desde México", " | ".join(regions) or official
    if explicit:
        return "Remoto desde México", explicit[0]
    return None


def _areas(offer: dict, sectors: dict, exclude: str) -> list[str]:
    title = offer.get("title") or ""
    context = normalize(" ".join(str(offer.get(field) or "") for field in ("company", "source", "text")))
    return [
        area for area, settings in sectors.items()
        if line_b.title_matches(title, [], {"keywords": settings.get("titles"), "exclude_titles": exclude})
        or (line_b.title_matches(title, [], {"keywords": settings.get("roles"), "exclude_titles": exclude})
            and any(re.search(rf"(?<!\w){re.escape(normalize(word))}(?!\w)", context)
                    for word in settings.get("context") or []))
    ]


def _open(offer: dict) -> bool:
    end = offer.get("valid_through")
    if end:
        try:
            if date.fromisoformat(str(end)[:10]) < date.today():
                return False
        except ValueError:
            return False
    return not CLOSED.search(normalize(offer.get("text")))


def _csv_value(value):
    """Evita que Excel interprete texto de la vacante como una fórmula."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def search(ws: Workspace, profile: Profile, requested: list[str], out: Path, say=print) -> tuple[int, int]:
    path = ws.root / CONFIG
    cfg = load_yaml(path if path.exists() else PACKAGE_ROOT / CONFIG)
    sectors = cfg["areas"]
    unknown = set(requested) - sectors.keys()
    if unknown:
        raise ValueError("Áreas disponibles: " + ", ".join(sectors))
    selected = {key: sectors[key] for key in requested} if requested else sectors
    line = dict(cfg["feeds"])
    missing = [name for name in line["sources"] if sources.get(name) is None]
    if missing:
        raise ValueError("Fuentes desconocidas: " + ", ".join(missing))
    line["keywords"] = list(dict.fromkeys(
        word for sector in sectors.values() for field in ("titles", "roles") for word in sector.get(field) or []
    ))
    line["exclude_titles"] = cfg.get("exclude_titles", "")
    line["world_scan"] = False

    offers, stats = line_b.collect_offers(ws, line, say=say, use_linkedin=False)
    if not any(isinstance(count, int) for count in stats.values()):
        raise ValueError("Las fuentes no respondieron. Vuelve a intentar más tarde.")

    rows, seen = [], set()
    for offer in offers:
        url = str(offer.get("apply_url") or offer.get("url") or "")
        if urlparse(url).scheme != "https" or not urlparse(url).hostname or not offer.get("title"):
            continue
        areas = _areas(offer, selected, line["exclude_titles"])
        location = _location(offer)
        if not areas or not location or not _open(offer):
            continue
        key = line_b.fingerprint(offer.get("company"), offer["title"]), location[0]
        if key in seen:
            continue
        seen.add(key)

        job = job_intel.analyze(offer.get("text") or offer["title"], profile.tax, title=offer["title"],
                                company=offer.get("company"), url=url, job_id="busqueda-mx",
                                meta=offer.get("salary"))
        fit = evidence.match(job, profile, profile.tax)
        rows.append({
            "cargo": job["title"], "empresa": job["company"], "areas": ", ".join(areas),
            "modalidad": location[0], "ubicacion_publicada": location[1], "score": fit["score"],
            "obligatorios_%": fit["required_coverage"],
            "habilidades_respaldadas": ", ".join(r["name"] for r in fit["rows"] if r["status"] == "backed"),
            "requisitos_por_validar": ", ".join(
                r["name"] for r in fit["rows"] if r["status"] != "backed" and r["importance"] == "required"
            ),
            "sueldo_publicado": job_intel.format_salary(job["salary"]), "fuente": offer["source"],
            "consultada": date.today().isoformat(), "url": url,
        })
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter=";")
        writer.writeheader()
        for row in sorted(rows, key=lambda item: -item["score"]):
            writer.writerow({key: _csv_value(value) for key, value in row.items()})
    return len(rows), len(offers)
