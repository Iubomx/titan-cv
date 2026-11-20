"""Centro de mando: refleja solo el estado real que informa el motor; se adapta a cualquier tamaño."""
import io

import pytest

pytest.importorskip("rich")

from rich.console import Console

from cvtitan import telemetry
from cvtitan.ui.dashboard import MODES, CommandCenter
from cvtitan.ui.event_stream import EventStream
from cvtitan.ui.matrix_animation import MatrixRain, boot
from cvtitan.ui.system_monitor import SystemMonitor, human_bytes


@pytest.fixture(autouse=True)
def fresh_state():
    telemetry.STATE.reset()
    telemetry.STATE.listeners.clear()
    yield
    telemetry.STATE.reset()
    telemetry.STATE.listeners.clear()


def _render(width, height, mode="apply", history=None):
    console = Console(width=width, height=height, record=True, file=io.StringIO(), color_system=None)
    cc = CommandCenter(mode=mode, history_provider=lambda: history or {}, console=console, screen=False,
                       monitor=SystemMonitor(interval=0))
    console.print(cc.render(), height=height)
    return console.export_text()


def test_without_engine_events_no_metric_is_invented():
    text = _render(160, 48)
    assert "Offers discovered" in text and "Awaiting events" in text
    assert "TITAN-SCOUT" in text and "STANDBY" in text          # los 7 agentes, en espera
    for agent in telemetry.AGENTS:
        assert agent in text


def test_engine_events_drive_counters_agents_and_alerts():
    telemetry.agent("Scout de portales", "ACTIVO", "8 sources")     # nombre interno -> TITAN-SCOUT
    telemetry.count("discovered", 829)
    telemetry.count("duplicates", 72)
    telemetry.explored(countries=["Chile"], cities=["Santiago"])
    telemetry.apply_begin(3)
    for r in ("applied: Application submitted and confirmed by the platform.", "pending: CAPTCHA",
              "done: already sent (not re-sent)"):
        telemetry.apply_result(r)
    telemetry.log("error: RuntimeError boom")
    s = telemetry.snapshot()
    assert s["agents"]["TITAN-SCOUT"] == ("ACTIVE", "8 sources")
    assert s["agents"]["TITAN-RADAR"][0] == "ACTIVE" and s["agents"]["TITAN-SHIELD"][0] == "ACTIVE"
    assert s["counters"] == {"discovered": 829, "duplicates": 72, "applied": 1, "pending": 1, "done_before": 1}
    assert s["alerts"][-1][1] == "error"
    text = _render(160, 48, history={"total": 15, "today": 2, "daily_max": 25})
    assert "829" in text and "73" in text and "3/3" in text and "2/25" in text   # 72 duplicados + 1 ya enviada


@pytest.mark.parametrize("size", [(220, 60), (160, 48), (120, 36), (100, 30), (70, 24)])
@pytest.mark.parametrize("mode", list(MODES))
def test_adapts_to_terminal_size_in_every_mode(size, mode):
    telemetry.log("[1/2] https://example.com/job")
    assert len(_render(*size, mode=mode).splitlines()) == size[1]


def test_event_stream_is_non_blocking_and_counts_rate():
    stream = EventStream(window=60).start()
    for i in range(5):
        telemetry.log(f"event {i}")
    assert stream.pending() == 5 and stream.drain() == 5
    assert stream.total == 5 and stream.rate_per_min() == 5
    stream.stop()
    telemetry.log("after stop")
    assert stream.pending() == 0


def test_listener_failure_never_breaks_engine():
    telemetry.subscribe(lambda ev: 1 / 0)
    telemetry.count("discovered", 1)                                     # no levanta excepción
    assert telemetry.snapshot()["counters"]["discovered"] == 1


def test_prints_inside_command_center_become_events():
    console = Console(width=120, height=36, file=io.StringIO(), color_system=None)
    with CommandCenter(console=console, screen=False, monitor=SystemMonitor(interval=0)):
        print("[2/4] Role filter and de-duplication")
    assert any("Role filter" in e[2] for e in telemetry.snapshot()["events"])


def test_system_monitor_reports_real_process_metrics():
    m = SystemMonitor(interval=0).sample()
    if not m:
        pytest.skip("psutil not installed")
    assert m["proc_mem"] > 0 and 0 <= m["sys_mem_pct"] <= 100 and m["threads"] >= 1
    assert human_bytes(1536) == "2 KB" and human_bytes(None) == "—"


def test_matrix_rain_and_boot_run_real_checks():
    rain = MatrixRain(20, 6, seed=1)
    for _ in range(10):
        rain.step()
    assert len(rain.render().plain.splitlines()) == 6
    console = Console(width=100, height=30, file=io.StringIO(), color_system=None)
    calls = []
    results = boot(console, [("ok check", lambda: (calls.append(1) or True, "fine")),
                             ("broken check", lambda: 1 / 0)], "APPLY MODE", rain_seconds=0.01)
    assert calls == [1]
    assert results[0][1] is True and results[1][1] is False and "ZeroDivisionError" in results[1][2]


def test_code_helmet_reveals_flows_and_stays_text_only():
    from cvtitan.ui.ascii_helmet import MASK_LARGE, HelmetAnimator, code_corpus
    assert "def " in code_corpus() and len(code_corpus()) > 1000              # código real de TITAN CV
    a = HelmetAnimator(MASK_LARGE, seed=1, glitch=0)
    half, full = a.frame(0.0, 0.5).plain, a.frame(0.0, 1.0).plain
    assert sum(c not in " 01\n" for c in half) < sum(c not in " 01\n" for c in full)   # se revela por escaneo
    assert a.frame(0.0, 1.0).plain != a.frame(2.0, 1.0).plain                  # el código fluye
    assert a.frame(0.0, still=True).plain == a.frame(9.0, still=True).plain    # quieto al terminar
    assert len(full.splitlines()) == len(MASK_LARGE) and full.isascii()        # solo texto


def test_aggressive_effects_never_break_the_helmet_outline():
    from cvtitan.ui.ascii_helmet import MASK_LARGE, HelmetAnimator
    a = HelmetAnimator(MASK_LARGE, seed=7, intensity=1.0, sway=1)
    pad = int(a.sway) + 3
    for i in range(200):                                   # incluye varias ráfagas de glitch
        rows = a.frame(i * 0.037, 1.0).plain.split("\n")
        for x, y in a.edge:
            window = rows[y][max(0, x + pad - 1): x + pad + 2]
            assert window.strip(), f"contorno perdido en ({x},{y}) cuadro {i}"
