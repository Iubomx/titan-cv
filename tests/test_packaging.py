"""Empaquetado: copia del código fuente vs instalación, y que el wheel pueda llevar todos los datos (sin red)."""
from pathlib import Path

from cvtitan import utils

ROOT = Path(__file__).resolve().parents[1]


def test_source_checkout_is_detected():
    assert utils.IS_CHECKOUT is True
    assert utils.PACKAGE_ROOT == ROOT and (utils.PACKAGE_ROOT / "config" / "skills_taxonomy.yaml").exists()


def test_installed_copy_uses_the_current_directory_as_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "IS_CHECKOUT", False)
    monkeypatch.delenv("CVTITAN_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    assert utils.Workspace.resolve(None).root == tmp_path.resolve()


def test_cvtitan_home_and_explicit_root_win_over_the_default(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "IS_CHECKOUT", False)
    home, other = tmp_path / "home", tmp_path / "other"
    home.mkdir()
    other.mkdir()
    monkeypatch.setenv("CVTITAN_HOME", str(home))
    assert utils.Workspace.resolve(None).root == home.resolve()
    assert utils.Workspace.resolve(other).root == other.resolve()


def test_checkout_default_workspace_is_the_repo_root(monkeypatch, tmp_path):
    monkeypatch.delenv("CVTITAN_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    assert utils.Workspace.resolve(None).root == ROOT


def test_every_config_file_is_covered_by_the_package_data_patterns():
    """pyproject empaqueta config/*.yaml y config/*.json: un archivo con otra extensión no viajaría en el wheel."""
    extensions = {p.suffix for p in (ROOT / "config").iterdir() if p.is_file()}
    assert extensions <= {".yaml", ".json"}, extensions


def test_templates_ship_with_the_package():
    declared = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"cvtitan.resources.config" = "config"' in declared
    assert '"cvtitan.resources.candidate" = "candidate"' in declared
    assert '"examples/*.example.yaml"' in declared
    assert list((ROOT / "candidate" / "examples").glob("*.example.yaml"))


def test_resource_paths_do_not_assume_the_source_layout():
    """Ningún módulo debe calcular config/ con `parents[N]` desde su propio archivo (rompería al instalar)."""
    offenders = []
    for path in (ROOT / "cvtitan").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if ('"config"' in text or '"candidate"' in text) and "__file__).resolve().parents[" in text:
            offenders.append(path.name)
    assert not offenders, offenders
