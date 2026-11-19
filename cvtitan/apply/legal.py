"""Guardián de respuestas legales y migratorias.

Reglas:
1. Ninguna pregunta de ciudadanía, residencia, autorización de trabajo, patrocinio, clearance o antecedentes se
   responde con heurísticas: solo con candidate/declarations.yaml (confirmado por el candidato).
2. Las casillas de «acepto/declaro/certifico» solo se marcan si son un CONSENTIMIENTO (aviso de privacidad,
   términos, veracidad de la información). Una casilla que certifica un HECHO (ciudadanía, antecedentes…) se
   decide con las declaraciones; si el hecho es falso o desconocido, no se marca.
3. Ante la duda: `None` (pendiente). Nunca se inventa.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..utils import load_yaml, normalize

# ---------------------------------------------------------------- países
COUNTRIES = {
    "Estados Unidos": r"united states|\bu\.?\s?s\.?\s?a?\b|\busa\b|estados unidos|\beeuu\b|ee\.?\s?uu|american|norteamerican",
    "Chile": r"\bchile\b|chilen[oa]",
    "Canadá": r"canada|canadian|canadiense",
    "México": r"mexico|mexican",
    "Colombia": r"colombia",
    "Perú": r"\bperu\b",
    "Argentina": r"argentin",
    "Brasil": r"brazil|brasil",
    "España": r"spain|espana|spanish citizen",
    "Alemania": r"germany|alemania|german",
    "Reino Unido": r"united kingdom|\buk\b|britain|british",
    "Unión Europea": r"\beu\b|european union|union europea|\beea\b",
    "Australia": r"australia",
}

COUNTRY_EN = {"Estados Unidos": "the United States", "Canadá": "Canada", "México": "Mexico", "Perú": "Peru",
              "Brasil": "Brazil", "España": "Spain", "Alemania": "Germany", "Reino Unido": "the United Kingdom",
              "Unión Europea": "the European Union"}

# ---------------------------------------------------------------- categorías
CITIZEN = r"citizen|ciudadan|nacionalidad|green card|permanent resident|residente permanente|u\.?s\.? person|\bnational\b"
RESIDENCE = r"reside|residing|residencia|resident\b|residente|live in|living in|currently located|based in"
AUTHORIZATION = (r"authoriz|autoriz|permiso de trabajo|work permit|eligible to work|right to work|legally (able|allowed|"
                 r"entitled)|lawfully|permitido trabajar|habilitado para trabajar")
SPONSORSHIP = r"sponsor|patrocin|\bvisa\b|h-?1b"
CLEARANCE = r"clearance|habilitacion de seguridad|top secret|\bts/sci\b"
UNKNOWN_FACTS = (r"antecedentes|criminal|felon|convicted|condenad|background check|drug (test|screen)|examen de drogas|"
                 r"non-?compete|no competencia")
NEGATED = r"\bwithout\b|\bsin\b|\bnot require|no requier|no necesit"

# Consentimientos que sí se pueden aceptar para postular.
CONSENT = (r"aviso de privacidad|politica de privacidad|privacy (policy|notice|statement)|data privacy|"
           r"tratamiento de (mis )?datos|"
           r"data processing|terminos y condiciones|terms (and|&) conditions|terms of (use|service)|"
           r"he leido|have read|i acknowledge|acknowledge that|reconozco|"
           r"informacion (proporcionada|entregada|suministrada)? ?es (veraz|verdadera|correcta|fidedigna)|"
           r"information (provided|submitted|given)? ?(is|are) (true|accurate|correct|complete)|"
           r"consiento|consent to|autorizo (el|a) (uso|tratamiento|contacto)|contact me|contactarme")
# Verbos de declaración: si aparecen junto a un hecho legal, NO es un simple consentimiento.
DECLARATION_VERB = r"certif|declar|attest|confirm|afirmo|i am|soy|tengo|i have|i hold|cuento con"


def load_declarations(path: Path) -> dict:
    return load_yaml(path) if path.exists() else {}


def countries_in(text: str) -> list[str]:
    return [c for c, rx in COUNTRIES.items() if re.search(rx, text)]


def _category(label: str) -> str | None:
    for name, rx in (("clearance", CLEARANCE), ("unknown", UNKNOWN_FACTS), ("sponsorship", SPONSORSHIP),
                     ("citizen", CITIZEN), ("authorization", AUTHORIZATION), ("residence", RESIDENCE)):
        if re.search(rx, label):
            return name
    return None


def _truth(cat: str, countries: list[str], decl: dict, job: dict, label: str) -> bool | None:
    """Verdad de la afirmación de la pregunta según las declaraciones (None = desconocida)."""
    if cat == "clearance":
        return bool(decl.get("security_clearance")) if "security_clearance" in decl else None
    if cat == "unknown":
        return None
    if not countries:                         # sin país en la pregunta: usar el país de la vacante
        jc = (job or {}).get("country")
        if jc:
            countries = [jc]
    if not countries:
        return None
    lists = {"citizen": decl.get("citizenship"), "residence": decl.get("legal_residence"),
             "authorization": decl.get("work_authorization")}
    if cat in lists:
        have = {normalize(x) for x in lists[cat] or []}
        if not have:
            return None
        # «U.S. citizen or permanent resident»: verdadero si se cumple para alguno de los países nombrados.
        return any(normalize(c) in have for c in countries)
    if cat == "sponsorship":
        if "needs_sponsorship_outside_authorized" not in decl:
            return None
        authorized = {normalize(x) for x in decl.get("work_authorization") or []}
        needs = any(normalize(c) not in authorized for c in countries) and decl["needs_sponsorship_outside_authorized"]
        # «¿Puedes trabajar SIN patrocinio?» pregunta lo contrario.
        return (not needs) if re.search(NEGATED, label) else needs
    return None


def _yes_no(options: list[str] | None, truth: bool, english: bool) -> str | None:
    yes = ("yes", "si", "sí", "true", "i am", "i do", "i will", "i have", "i can")
    no = ("no", "false", "i am not", "i do not", "i will not", "i don't", "i cannot")
    if options:
        for o in options:
            n = normalize(o)
            if truth and (n in yes or n.startswith(("yes", "si,", "sí,", "si ", "sí "))):
                return o
            if not truth and (n in no or n.startswith(("no,", "no ", "i am not", "i do not", "i will not"))):
                return o
        return None
    return ("Yes" if truth else "No") if english else ("Sí" if truth else "No")


def legal_answer(field: dict, label: str, decl: dict, job: dict) -> tuple[bool, str | None, str]:
    """(¿es una pregunta legal/consentimiento?, valor o None, motivo).
    Si el primer elemento es True, rule_value debe devolver el valor tal cual (None = pendiente)."""
    t = field.get("type")
    cat = _category(label)
    is_consent = bool(re.search(CONSENT, label))
    if t == "checkbox":
        if cat and (cat != "unknown" or not is_consent) and re.search(DECLARATION_VERB + "|" + CITIZEN, label):
            truth = _truth(cat, countries_in(label), decl, job, label)
            if truth is True:
                return True, "sí", f"declaración confirmada ({cat})"
            return True, None, f"declaración {cat} {'falsa' if truth is False else 'no confirmada'}: no se marca"
        if is_consent:
            return True, "sí", "consentimiento (aviso o veracidad)"
        if re.search(r"acepto|agree|declaro|certif|autorizo", label):
            return True, None, "declaración no reconocida: requiere revisión"
        return False, None, ""
    if not cat:
        return False, None, ""
    if t in ("text", "textarea") and cat == "citizen" and re.search(r"cual|which|what|indique|pais|country", label):
        cits = decl.get("citizenship") or []
        return True, (", ".join(cits) if cits else None), "ciudadanía declarada"
    truth = _truth(cat, countries_in(label), decl, job, label)
    if truth is None:
        return True, None, f"{cat}: sin declaración aplicable"
    if truth is False and cat in ("residence", "authorization", "citizen") and field.get("required") \
            and countries_in(label) and "Chile" not in countries_in(label):
        what = {"residence": "residence", "authorization": "work authorization", "citizen": "citizenship"}[cat]
        field["_ineligible"] = f"requires {what} in {', '.join(COUNTRY_EN.get(c, c) for c in countries_in(label))}"
    english = bool(re.search(r"\b(are|do|will|you|your|the)\b", label))
    return True, _yes_no(field.get("options"), truth, english), f"{cat} según declaraciones"


# ---------------------------------------------------------------- ¿se puede trabajar desde Chile?
REMOTE_BLOCKERS = [
    (r"\b(us|u\.s\.|usa|united states|canada|uk|eu|europe|germany|spain|mexico|colombia)[- ]?(only|based)\b", "solo residentes de ese país"),
    (r"must (be )?(located|based|reside|live|living) in (the )?(us|u\.s\.|usa|united states|canada|uk|europe|eu|"
     r"germany|spain|mexico|colombia|[a-z]+ state)", "exige residir en otro país"),
    (r"(legally )?authori[sz]ed to work in (the )?(us|u\.s\.|usa|united states|canada|uk|eu|europe|germany|spain)",
     "exige autorización de trabajo extranjera"),
    (r"(us|u\.s\.) citizen(s|ship)? (only|required)|citizenship (is )?required|green card", "exige ciudadanía"),
    (r"security clearance|active clearance|ts/sci|\bitar\b|u\.s\. person", "exige clearance/ITAR"),
    (r"(no|not|unable to|will not|won't|cannot|can't) (provide |offer )?(visa )?sponsor", "no ofrece patrocinio"),
    (r"without (the need for )?(visa )?sponsorship", "no ofrece patrocinio"),
    (r"remote \((us|usa|united states|canada|uk|eu)\)|remote - (us|usa|united states)", "remoto restringido a otro país"),
]
REMOTE_OPEN = (r"latam|latin america|south america|sudamerica|americas|worldwide|anywhere|global(ly)? remote|"
               r"work from anywhere|any country|international (applicants|candidates)|\bchile\b|chile eligible|remote latam|"
               r"remote.{0,20}(latam|latin|americas|worldwide)")


def remote_eligibility(text: str, country: str | None, modality: str | None) -> str:
    """'ok: …' | 'excluido: …' | 'ambiguo' — ¿puede el candidato trabajar desde Chile sin trasladarse?"""
    if (country or "") == "Chile":
        return "ok: Chile"
    t = normalize(text or "")[:12000]
    for rx, why in REMOTE_BLOCKERS:
        m = re.search(rx, t)
        if m:
            return f"excluido: {why} («{m.group(0)[:60]}»)"
    if modality in ("presencial", "híbrido") and country:
        return f"excluido: {modality} fuera de Chile ({country})"
    if re.search(REMOTE_OPEN, t):
        return "ok: remoto abierto a LATAM/global"
    return "ambiguo"
