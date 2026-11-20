"""Humo de los comandos movidos a cvtitan/commands/: ejecutan sus imports diferidos y rutas básicas (sin red)."""
import shutil

import pytest

from cvtitan.cli import main
from cvtitan.utils import Workspace

REPO = Workspace.resolve(None)


@pytest.fixture
def root(tmp_path):
    (tmp_path / "candidate").mkdir()
    shutil.copy(REPO.example_profile_path, tmp_path / "candidate" / "profile.yaml")
    return str(tmp_path)


def test_validate_example_profile(root, capsys):
    assert main(["--root", root, "validate"]) == 0
    assert "Profile is valid." in capsys.readouterr().out


def test_jobs_and_track_on_empty_workspace(root, capsys):
    assert main(["--root", root, "jobs"]) == 0
    assert main(["--root", root, "track", "list"]) == 0
    assert main(["--root", root, "track", "stats"]) == 0
    capsys.readouterr()


def test_track_add_requires_a_job_id(root):
    assert main(["--root", root, "track", "add"]) == 2


def test_match_for_unknown_job_fails_cleanly(root):
    assert main(["--root", root, "match", "does-not-exist"]) == 2


def test_informe_historial_on_empty_database(root, capsys):
    assert main(["--root", root, "informe", "--historial"]) == 0
    assert "Applications: 0" in capsys.readouterr().out


def test_informe_without_reports_fails_cleanly(root):
    assert main(["--root", root, "informe"]) == 2


def test_informe_unknown_ref_fails_cleanly(root):
    assert main(["--root", root, "informe", "--ref", "JOB-00000000"]) == 2


@pytest.mark.parametrize("action", ["estado", "importar", "recuperar"])
def test_registro_actions(root, capsys, action):
    assert main(["--root", root, "registro", action]) == 0
    assert "Global registry:" in capsys.readouterr().out


def test_mercado_without_search_list_fails_cleanly(root):
    assert main(["--root", root, "mercado"]) == 2


def test_help_lists_every_migrated_command(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for name in ("validate", "import-cv", "analyze", "generate", "track", "informe", "registro", "mercado", "purge",
                 "init", "preview", "schema", "llmlog"):
        assert name in out
