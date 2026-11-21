"""Diff del CV adaptado contra los hechos del perfil: qué se reescribió, qué se añadió y qué fuente falta.

Cada bloque del borrador (`cv_draft.yaml`) conserva su `source`. Aquí se compara su texto con el hecho original
del perfil para que el candidato vea de un vistazo lo que cambió antes de enviar el CV.
"""
from __future__ import annotations

import difflib
import re
from html import escape as esc

from .cv_writer import render_html
from .profile import Profile

NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in NUMBER.findall(text or "")}


def _original(source: str, profile: Profile) -> str | None:
    if source == "summary":
        return profile.data.get("summary")
    if source.startswith("summary:"):
        variant = source.split(":", 1)[1]
        return next((v.get("text") for v in profile.data.get("summary_variants") or [] if v.get("id") == variant), None)
    item = profile.evidence().get(source)
    return item["text"] if item else None


def _blocks(draft: dict):
    """(sección, source, texto) de los bloques redactados del borrador."""
    s = draft.get("summary") or {}
    yield "summary", s.get("source", ""), s.get("text", "")
    for exp in draft.get("experience") or []:
        for b in exp.get("bullets") or []:
            yield "experience", b.get("source", ""), b.get("text", "")
    for pr in draft.get("projects") or []:
        yield "projects", pr.get("source", ""), pr.get("text", "")


def diff_draft(draft: dict, profile: Profile) -> list[dict]:
    """Un registro por bloque: {section, source, original, current, status, added_numbers}.

    status: `unchanged` | `edited` | `unknown_source` (la fuente no existe en el perfil).
    `added_numbers`: cifras del texto actual que NO están en el original (posible invención).
    """
    out = []
    for section, source, current in _blocks(draft):
        original = _original(source, profile) if source else None
        if original is None:
            out.append({"section": section, "source": source, "original": None, "current": current,
                        "status": "unknown_source", "added_numbers": sorted(_numbers(current))})
            continue
        same = " ".join(original.split()) == " ".join(current.split())
        out.append({"section": section, "source": source, "original": original, "current": current,
                    "status": "unchanged" if same else "edited",
                    "added_numbers": sorted(_numbers(current) - _numbers(original))})
    return out


def word_diff_html(old: str, new: str) -> str:
    a, b = old.split(), new.split()
    parts = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if op == "equal":
            parts.append(esc(" ".join(a[i1:i2])))
            continue
        if i2 > i1:
            parts.append(f"<del>{esc(' '.join(a[i1:i2]))}</del>")
        if j2 > j1:
            parts.append(f"<ins>{esc(' '.join(b[j1:j2]))}</ins>")
    return " ".join(p for p in parts if p)


def summarize(changes: list[dict]) -> dict:
    return {"blocks": len(changes), "unchanged": sum(c["status"] == "unchanged" for c in changes),
            "edited": sum(c["status"] == "edited" for c in changes),
            "unknown_source": sum(c["status"] == "unknown_source" for c in changes),
            "with_new_numbers": sum(bool(c["added_numbers"]) for c in changes)}


def preview_html(draft: dict, changes: list[dict]) -> str:
    """El HTML del CV más un panel de revisión (no se imprime) con lo editado y lo que requiere atención."""
    flagged = [c for c in changes if c["status"] != "unchanged"]
    rows = []
    for c in flagged:
        alerts = []
        if c["status"] == "unknown_source":
            alerts.append("fuente inexistente en el perfil")
        if c["added_numbers"]:
            alerts.append("cifras nuevas: " + ", ".join(c["added_numbers"]))
        body = word_diff_html(c["original"], c["current"]) if c["original"] is not None else esc(c["current"])
        rows.append(f"<tr class='{'warn' if alerts else ''}'><td>{esc(c['section'])}<br><small>{esc(c['source'])}</small></td>"
                    f"<td>{body}</td><td>{esc('; '.join(alerts))}</td></tr>")
    stats = summarize(changes)
    panel = (
        "<style>.review{font:13px Arial,sans-serif;margin:24px auto;max-width:900px;border-top:3px solid #888;padding-top:8px}"
        ".review table{border-collapse:collapse;width:100%}.review td{border:1px solid #ccc;padding:4px 6px;vertical-align:top}"
        ".review ins{background:#d4f5d4;text-decoration:none}.review del{background:#fbd5d5}"
        ".review tr.warn td{background:#fff6dd}@media print{.review{display:none}}</style>"
        f"<section class='review'><h2>Revisión (no se imprime)</h2><p>{stats['edited']} bloques reescritos, "
        f"{stats['unchanged']} idénticos al perfil, {stats['unknown_source']} sin fuente, "
        f"{stats['with_new_numbers']} con cifras nuevas.</p>"
        + ("<table><tr><th>Bloque</th><th>Cambio (rojo = original, verde = actual)</th><th>Atención</th></tr>"
           + "".join(rows) + "</table>" if rows else "<p>Sin cambios respecto al perfil.</p>")
        + "</section>")
    return render_html(draft).replace("</body>", panel + "</body>")
