"""Mejoras de la auditoría 2026-11-18: cortacircuitos por portal, registro de ejecución y retención."""
import os
import time
import types

from cvtitan import telemetry


def test_platform_circuit_breaker_trips_after_same_structural_failure():
    from cvtitan.apply.batch import BatchApplier
    fake = types.SimpleNamespace(failures={}, tripped={}, say=lambda *a: None,
                                 STRUCTURAL=BatchApplier.STRUCTURAL, TRIP_AFTER=BatchApplier.TRIP_AFTER)
    track = BatchApplier._track_failure.__get__(fake)
    track("getonboard", "Get on Board", "pending: 4 question(s) I cannot answer from your profile.")   # no estructural
    assert not fake.tripped
    for _ in range(2):
        track("getonboard", "Get on Board", "pending: Unsure how to continue on this page. Advance manually")
    assert not fake.tripped
    track("getonboard", "Get on Board", "pending: Unsure how to continue on this page. Advance manually")
    assert "getonboard" in fake.tripped
    track("generic", "Web", "error: TimeoutError")                                        # sitios sueltos: nunca
    track("generic", "Web", "error: TimeoutError")
    track("generic", "Web", "error: TimeoutError")
    assert "generic" not in fake.tripped


def test_every_run_is_recorded_to_a_log(tmp_path):
    telemetry.STATE.reset()
    close = telemetry.record_to(tmp_path / "runs" / "run.log")
    telemetry.agent("TITAN-SCOUT", "ACTIVE", "x")
    telemetry.log("[1/4] International sources")
    telemetry.stage("LINE B", 1, 4, "Scanning")
    telemetry.apply_result("applied: Application submitted and confirmed by the platform.")
    close()
    telemetry.log("after close")
    text = (tmp_path / "runs" / "run.log").read_text(encoding="utf-8")
    assert "TITAN-SCOUT" in text and "International sources" in text and "EVENT stage" in text
    assert "EVENT apply_result" in text and "after close" not in text


def test_diagnostics_with_personal_data_are_purged_after_30_days(tmp_path):
    from cvtitan.cli import purge_diagnostics
    ws = types.SimpleNamespace(root=tmp_path)
    old, new = tmp_path / "data/outputs/job1", tmp_path / "data/outputs/job2"
    for d in (old, new):
        d.mkdir(parents=True)
        for name in ("debug_page.html", "debug_fields.json", "confirmacion.png"):
            (d / name).write_text("x")
    past = time.time() - 31 * 86400
    for name in ("debug_page.html", "debug_fields.json", "confirmacion.png"):
        os.utime(old / name, (past, past))
    assert purge_diagnostics(ws) == 2
    assert not (old / "debug_page.html").exists() and (old / "confirmacion.png").exists()   # evidencia se conserva
    assert (new / "debug_page.html").exists()


def test_no_control_characters_in_source_or_config():
    """Regresión: escapes como \b mal copiados terminaban como bytes de control dentro de regex."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    bad = []
    for p in list((root / "cvtitan").rglob("*.py")) + list((root / "config").glob("*.yaml")):
        data = p.read_bytes()
        if any(b in data for b in (bytes([8]), bytes([0]), bytes([27]))):
            bad.append(p.name)
    assert not bad, f"caracteres de control en: {bad}"


def test_registry_block_does_not_rewrite_vacancy_status():
    """Regresión 2026-11-18: saltar una vacante bloqueada («awaiting human review») la marcaba CLOSED."""
    from cvtitan.apply.batch import BatchApplier
    calls = []
    reg = types.SimpleNamespace(by_url=lambda u: {"id": 7, "status": "PENDING_REVIEW"},
                                can_submit=lambda i: (False, "awaiting human review"),
                                set_status=lambda i, s: calls.append(s))
    fake = types.SimpleNamespace(registry=reg)
    fake._process_inner = BatchApplier._process_inner.__get__(fake)
    result = BatchApplier._process.__get__(fake)("https://example.com/job/1")
    assert result.startswith("skipped: awaiting human review") and calls == []
