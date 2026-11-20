"""`cvtitan init`: plantillas por rubro y asistente guiado (datos ficticios)."""
import pytest

from cvtitan.cli import main
from cvtitan.commands.init import guided_profile, templates
from cvtitan.profile import Profile
from cvtitan.taxonomy import Taxonomy
from cvtitan.utils import Workspace, load_yaml

REPO = Workspace.resolve(None)


def test_expected_templates_exist():
    assert {"software", "comercial", "salud"} <= set(templates(REPO))


@pytest.mark.parametrize("name", ["software", "comercial", "salud"])
def test_every_template_is_a_valid_profile(name):
    tax = Taxonomy.load(REPO.taxonomy_path)
    profile = Profile.load(templates(REPO)[name], tax)
    errors, _ = profile.validate()
    assert errors == []
    assert profile.backed_keys()                       # tiene skills respaldadas
    assert all(s["status"] == "backed" or s["status"] == "to_demonstrate" for s in profile.skill_map.values())


@pytest.mark.parametrize("name", ["software", "comercial", "salud"])
def test_templates_contain_only_fictitious_contact_data(name):
    data = load_yaml(templates(REPO)[name])
    assert data["personal"]["email"].endswith("@example.com")


def test_list_templates(capsys):
    assert main(["init", "--listar"]) == 0
    assert "software" in capsys.readouterr().out


def test_init_with_template_copies_it(tmp_path):
    assert main(["--root", str(tmp_path), "init", "--plantilla", "salud"]) == 0
    assert load_yaml(tmp_path / "candidate" / "profile.yaml")["personal"]["name"] == "Camilo Reyes Navarro"
    assert (tmp_path / "data" / "jobs").is_dir()


def test_unknown_template_is_rejected_and_nothing_is_created(tmp_path):
    assert main(["--root", str(tmp_path), "init", "--plantilla", "nope"]) == 2
    assert not (tmp_path / "candidate" / "profile.yaml").exists()


def test_existing_profile_is_never_overwritten(tmp_path):
    (tmp_path / "candidate").mkdir()
    (tmp_path / "candidate" / "profile.yaml").write_text("personal: {name: Mine}\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "init", "--plantilla", "software"]) == 0
    assert load_yaml(tmp_path / "candidate" / "profile.yaml")["personal"]["name"] == "Mine"


def test_template_and_guided_together_are_rejected(tmp_path):
    assert main(["--root", str(tmp_path), "init", "--guiado", "--plantilla", "software"]) == 2


ANSWERS = ["Ana Pérez", "Analista", "ana@example.com", "", "Lima, Perú", "Perú", "PEN 6000", "Inmediata",
           "Perú", "Perú", "Perú"]


def test_guided_profile_only_keeps_what_was_answered():
    it = iter(ANSWERS)
    profile, declarations = guided_profile(lambda prompt: next(it))
    assert profile["personal"] == {"name": "Ana Pérez", "headline": "Analista", "email": "ana@example.com",
                                   "location": "Lima, Perú"}          # el teléfono vacío no se inventa
    assert profile["preferences"]["country"] == "Perú" and profile["skills"] == []
    assert declarations["citizenship"] == ["Perú"] and declarations["work_authorization"] == ["Perú"]


def test_guided_init_writes_valid_profile_and_declarations(tmp_path, monkeypatch):
    it = iter(ANSWERS)
    monkeypatch.setattr("builtins.input", lambda *_: next(it))
    assert main(["--root", str(tmp_path), "init", "--guiado"]) == 0
    ws = Workspace(tmp_path)
    profile = Profile.load(ws.profile_path, Taxonomy.load(REPO.taxonomy_path))
    assert profile.validate()[0] == []
    assert load_yaml(tmp_path / "candidate" / "declarations.yaml")["legal_residence"] == ["Perú"]


def test_guided_init_requires_a_name(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "")
    assert main(["--root", str(tmp_path), "init", "--guiado"]) == 2
    assert not (tmp_path / "candidate" / "profile.yaml").exists()
