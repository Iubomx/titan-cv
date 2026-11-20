"""cvtitan purge: borra solo lo generado en data/, por grupos, y nunca el perfil del candidato."""
import pytest

from cvtitan import purge
from cvtitan.cli import main
from cvtitan.utils import Workspace


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "candidate").mkdir()
    (tmp_path / "candidate" / "profile.yaml").write_text("personal: {name: Test}\n", encoding="utf-8")
    data = tmp_path / "data"
    (data / "outputs" / "job1").mkdir(parents=True)
    (data / "outputs" / "job1" / "cv.docx").write_text("x", encoding="utf-8")
    (data / "jobs" / "job1").mkdir(parents=True)
    (data / "browser-profile").mkdir()
    (data / "browser-profile" / "Cookies").write_text("x", encoding="utf-8")
    (data / "cvtitan.db").write_text("x", encoding="utf-8")
    (data / "auto" / "runs").mkdir(parents=True)
    (data / "market_cache.jsonl").write_text("{}\n", encoding="utf-8")
    return Workspace(tmp_path)


def test_plan_lists_only_existing_paths_of_requested_groups(ws):
    names = {p.name for p in purge.plan(ws, ["sessions"])}
    assert names == {"browser-profile"}


def test_unknown_group_is_rejected(ws):
    with pytest.raises(ValueError):
        purge.plan(ws, ["nope"])


def test_execute_removes_files_and_dirs(ws):
    paths = purge.plan(ws, ["outputs", "history", "cache", "sessions"])
    done, failed = purge.execute(paths)
    assert done == len(paths) and not failed
    assert not (ws.root / "data" / "outputs").exists()
    assert not (ws.root / "data" / "cvtitan.db").exists()


def test_candidate_profile_is_never_deleted(ws):
    purge.execute(purge.plan(ws, list(purge.GROUPS)))
    assert (ws.root / "candidate" / "profile.yaml").exists()


def test_cli_without_flags_deletes_nothing(ws, capsys):
    assert main(["--root", str(ws.root), "purge"]) == 2
    assert (ws.root / "data" / "cvtitan.db").exists()


def test_cli_si_deletes_selected_group_only(ws):
    assert main(["--root", str(ws.root), "purge", "--sesiones", "--si"]) == 0
    assert not (ws.root / "data" / "browser-profile").exists()
    assert (ws.root / "data" / "cvtitan.db").exists()


def test_cli_declined_confirmation_deletes_nothing(ws, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "no")
    assert main(["--root", str(ws.root), "purge", "--todo"]) == 1
    assert (ws.root / "data" / "cvtitan.db").exists()
