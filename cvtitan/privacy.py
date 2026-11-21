"""Privacidad en la terminal: ningún dato personal del candidato se muestra ni queda en los registros.

`redact(text)` reemplaza por etiquetas neutras:
  - los valores del perfil (candidate/profile.yaml -> personal): nombre completo y sus partes, correo, teléfono,
    ciudad, LinkedIn y GitHub;
  - y, por patrón, CUALQUIER correo, teléfono o RUT (por ejemplo, el correo al que un portal envió un código).
Se aplica a todo lo que imprime la CLI (salida de texto, centro de mando, modo demo) y a los registros y
informes que se guardan en data/auto/. Los formularios sí reciben los datos reales: solo se oculta la vista.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w/=.\-])\+\d[\d\s().-]{7,}\d(?![\w/])")     # solo con prefijo internacional
RUT = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")

_lock = threading.Lock()
_rules: list[tuple[re.Pattern, str]] | None = None
_profile_path: Path | None = None


def configure(profile_path: Path | None) -> None:
    """Indica de qué perfil salen los datos a ocultar (se carga una sola vez, de forma diferida)."""
    global _rules, _profile_path
    with _lock:
        _profile_path, _rules = profile_path, None


def _load() -> list[tuple[re.Pattern, str]]:
    global _rules
    with _lock:
        if _rules is not None:
            return _rules
        rules: list[tuple[str, str]] = []
        p: dict = {}
        try:
            if _profile_path is None:
                from .utils import PACKAGE_ROOT
                path = PACKAGE_ROOT / "candidate" / "profile.yaml"
            else:
                path = _profile_path
            if path.exists():
                from .utils import load_yaml
                p = (load_yaml(path) or {}).get("personal") or {}
        except Exception:
            p = {}
        for key, tag in (("email", "[EMAIL]"), ("linkedin", "[LINKEDIN]"), ("github", "[GITHUB]"),
                         ("phone", "[PHONE]"), ("location", "[CITY]")):
            v = str(p.get(key) or "").strip()
            if v:
                rules.append((v, tag))
                if key == "linkedin":
                    rules.append((v.split("/")[-1], tag))               # el identificador suelto
                if key == "location":
                    rules.append((v.split(",")[0].strip(), "[CITY]"))   # solo la ciudad
        names = [str(p.get(k) or "").strip() for k in ("name", "first_name", "last_name")]
        full, first, last = names
        variants = {full, f"{first} {last}".strip(), f"{first.split()[0] if first else ''} {last}".strip(), last,
                    f"{first.split()[0] if first else ''} {last.split()[0] if last else ''}".strip(), first,
                    last.split()[0] if last else ""}                  # primer apellido solo (distintivo)
        rules += [(v, "[NAME]") for v in variants if v and len(v) >= 4]
        rules.sort(key=lambda r: -len(r[0]))                          # primero lo más largo
        compiled = []
        digits = re.sub(r"\D", "", str(p.get("phone") or ""))
        if len(digits) >= 8:                                          # tu número en cualquier formato
            local = digits[-9:]
            sep = r"[\s.()-]*"
            compiled.append((re.compile(r"(?<!\d)(\+?" + sep.join(digits[:-9]) + sep + ")?" + sep.join(local)
                                        + r"(?!\d)"), "[PHONE]"))
        for value, tag in rules:
            if tag == "[NAME]":
                # Sin importar tildes, mayúsculas ni separadores: «José Andrés», «jose_andres», «JOSE-ANDRES».
                pat = r"[\s_.-]+".join(_accent_free(w) for w in value.split())
                compiled.append((re.compile(rf"(?i)(?<![^\W_]){pat}(?![^\W_])"), tag))
                continue
            pat = re.escape(value).replace(r"\ ", r"\s+")
            compiled.append((re.compile(rf"(?i)(?<![\w]){pat}(?![\w])"), tag))
        _rules = compiled
        return _rules


_ACCENTS = {"a": "aáàä", "e": "eéèë", "i": "iíìï", "o": "oóòö", "u": "uúùü", "n": "nñ"}


def _accent_free(word: str) -> str:
    """Patrón de una palabra que acepta la versión con o sin tildes."""
    import unicodedata
    base = "".join(c for c in unicodedata.normalize("NFD", word.lower()) if unicodedata.category(c) != "Mn")
    return "".join(f"[{_ACCENTS[c]}]" if c in _ACCENTS else re.escape(c) for c in base)


URL = re.compile(r"https?://[^\s\"'<>)\]|]+")


def ref(url: str) -> str:
    """Código estable y no reversible de una URL (p. ej. JOB-7F3A9C21). `cvtitan informe --ref` lo resuelve."""
    import hashlib
    return "JOB-" + hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:8].upper()


def mask_url(url: str) -> str:
    """Solo el dominio + el código: la ruta completa (que puede llevar identificadores) no se muestra."""
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower().removeprefix("www.") or "link"
    return f"{host} #{ref(url)}"


def resolve_ref(code: str, db_path: Path) -> list[str]:
    """URLs (del historial y del registro) cuyo código coincide con `code`."""
    import sqlite3
    code = code.strip().upper()
    code = code if code.startswith("JOB-") else "JOB-" + code
    found = []
    try:
        con = sqlite3.connect(str(db_path))
        urls = [r[0] for r in con.execute("SELECT url FROM applications WHERE url IS NOT NULL")]
        try:
            urls += [r[0] for r in con.execute("SELECT url FROM vacancy_sources WHERE url IS NOT NULL")]
        except Exception:
            pass
        con.close()
    except Exception:
        return []
    for u in dict.fromkeys(urls):
        if ref(u) == code:
            found.append(u)
    refs = db_path.parent / "auto" / "refs.json"          # ofertas del embudo que no llegaron al historial
    if not found and refs.exists():
        import json
        try:
            u = json.loads(refs.read_text(encoding="utf-8")).get(code)
            if u:
                found.append(u)
        except ValueError:
            pass
    return found


def redact(text: str) -> str:
    if not text:
        return text
    s = URL.sub(lambda m: mask_url(m.group(0)), str(text))
    for rx, tag in _load():
        s = rx.sub(tag, s)
    s = EMAIL.sub("[EMAIL]", s)
    s = RUT.sub("[RUT]", s)
    s = PHONE.sub("[PHONE]", s)
    return s


class RedactingStream:
    """Envuelve stdout/stderr: todo lo que se escribe pasa por `redact` (línea a línea)."""

    def __init__(self, stream):
        self.stream = stream
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        if "\n" in self._buf:
            head, self._buf = self._buf.rsplit("\n", 1)
            self.stream.write(redact(head) + "\n")
        return len(s)

    def flush(self) -> None:
        if self._buf:
            self.stream.write(redact(self._buf))
            self._buf = ""
        self.stream.flush()

    def isatty(self) -> bool:
        return getattr(self.stream, "isatty", lambda: False)()

    def __getattr__(self, name):
        return getattr(self.stream, name)
