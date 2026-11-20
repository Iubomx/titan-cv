"""Política de envío: send_enabled estricto y revisión humana por defecto (sin navegador ni red)."""
import pytest

from cvtitan.apply.batch import BatchApplier
from cvtitan.send_policy import decide
from cvtitan.utils import Workspace, load_yaml

REPO = Workspace.resolve(None)


def test_nothing_is_sent_by_default():
    d = decide({}, simulate=False, chosen=3)
    assert not d.send and "send_enabled: false" in d.reason and d.stage_label == "Sending disabled"


@pytest.mark.parametrize("value", [False, None, "true", "yes", 1, "si"])
def test_only_boolean_true_enables_sending(value):
    assert not decide({"send_enabled": value}, simulate=False, chosen=2).send


def test_enabled_line_sends_and_requires_review_by_default():
    d = decide({"send_enabled": True}, simulate=False, chosen=2)
    assert d.send and not d.auto_submit


@pytest.mark.parametrize("mode, auto", [("auto", True), ("AUTO", True), (" auto ", True), ("always", False),
                                        ("whatever", False), (None, False), ("", False)])
def test_review_mode_only_auto_skips_confirmation(mode, auto):
    line = {"send_enabled": True}
    if mode is not None:
        line["review_mode"] = mode
    assert decide(line, simulate=False, chosen=1).auto_submit is auto


def test_simulation_and_empty_selection_never_send():
    assert not decide({"send_enabled": True}, simulate=True, chosen=5).send
    d = decide({"send_enabled": True}, simulate=False, chosen=0)
    assert not d.send and d.stage_label == "Nothing to apply"


def test_missing_line_config_never_sends():
    assert not decide(None, simulate=False, chosen=1).send


def test_shipped_templates_are_safe_by_default():
    lines = load_yaml(REPO.root / "config" / "lines.yaml")["lines"]
    for key in ("A", "B"):
        assert lines[key]["send_enabled"] is False and lines[key]["review_mode"] == "always"


class _Row(dict):
    pass


class _FakeDB:
    def __init__(self):
        self.row = {"status": "awaiting_review", "status_detail": "", "url": "https://example.com/j/1", "data": {}}
        self.statuses = []

    def get(self, job_id):
        return self.row

    def set_status(self, job_id, status, detail=None):
        self.statuses.append((status, detail))


class _FakeRunner:
    pages: dict = {}

    def _start(self, job_id, force=False):
        pass

    def _submit(self, *a, **k):  # pragma: no cover - no debe llamarse
        raise AssertionError("no se debe enviar sin aprobación")


class _FakeRegistry:
    def by_url(self, url):
        return None


def _applier(auto_submit, unattended=True):
    a = BatchApplier.__new__(BatchApplier)
    a.db, a.runner, a.registry = _FakeDB(), _FakeRunner(), _FakeRegistry()
    a.auto_submit, a.unattended, a.force = auto_submit, unattended, True
    a.say = lambda *_: None
    a.ask = lambda *_: (_ for _ in ()).throw(AssertionError("no debe preguntar en modo desatendido"))
    a.job_id_for = lambda url: "job1"
    a._submit_once = lambda *_: (_ for _ in ()).throw(AssertionError("no debe enviar"))
    return a


def test_unattended_without_auto_submit_leaves_job_awaiting_review():
    a = _applier(auto_submit=False)
    result = a._process_inner("https://example.com/j/1")
    assert result.startswith("pending: awaiting your approval")
    assert a.db.statuses == [("awaiting_review", "Awaiting your approval (review_mode: always).")]
