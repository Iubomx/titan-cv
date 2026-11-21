"""Política de envío de una línea (A o B): ¿se puede enviar, y con revisión humana o automático?

Reglas (config/lines.yaml, por línea):
  - `send_enabled`: debe ser exactamente `true` para enviar algo. Por defecto `false`.
  - `review_mode`: `always` (por defecto) deja cada postulación lista en «awaiting_review» para que TÚ la apruebes
    (web o `cvtitan postular --pendientes --ver`); `auto` envía sin confirmación lo que cumple tus reglas.
    Cualquier otro valor se trata como `always`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SendDecision:
    send: bool            # ¿abrir el robot y procesar postulaciones?
    auto_submit: bool     # ¿enviar sin confirmación humana? (solo con review_mode: auto)
    reason: str           # mensaje para el registro cuando no se envía
    stage_label: str      # etiqueta del centro de mando


def decide(line: dict | None, simulate: bool, chosen: int, label: str = "Line A") -> SendDecision:
    line = line or {}
    auto = str(line.get("review_mode", "always")).strip().lower() == "auto"
    if simulate:
        return SendDecision(False, auto, "Simulation: nothing was submitted.", "Simulation · no submissions")
    if not chosen:
        return SendDecision(False, auto, "Nothing to apply to today.", "Nothing to apply")
    if line.get("send_enabled") is not True:
        return SendDecision(False, auto, f"{label} has send_enabled: false (requires your authorization). "
                                         "Nothing was submitted.", "Sending disabled")
    return SendDecision(True, auto, "", "Processing applications")
