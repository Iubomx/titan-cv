"""Internacionalización: catálogo coherente entre idiomas y mensajes de validación en es/en."""
import re
import string

import pytest

from cvtitan import i18n
from cvtitan.cli import main
from cvtitan.messages import MESSAGES


@pytest.fixture(autouse=True)
def reset_language(monkeypatch):
    monkeypatch.delenv("CVTITAN_LANG", raising=False)
    yield
    i18n.set_language(None)


def _placeholders(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_language_has_the_same_keys_and_placeholders_as_spanish():
    reference = MESSAGES["es"]
    for lang, catalog in MESSAGES.items():
        assert set(catalog) == set(reference), f"{lang}: claves distintas"
        for key, text in catalog.items():
            assert _placeholders(text) == _placeholders(reference[key]), f"{lang}.{key}: placeholders distintos"


def test_default_language_is_spanish():
    assert i18n.set_language(None) == "es"
    assert i18n.t("profile.name_required") == "personal.name es obligatorio."


def test_language_from_environment_and_locale_style_values(monkeypatch):
    monkeypatch.setenv("CVTITAN_LANG", "en_US")
    assert i18n.set_language(None) == "en"


def test_unknown_language_falls_back_to_spanish():
    assert i18n.set_language("xx") == "es"


def test_missing_key_returns_key_and_missing_placeholder_does_not_crash():
    assert i18n.t("no.such.key") == "no.such.key"
    assert "{section}" in i18n.t("profile.item_no_id")


def test_validate_command_follows_language(tmp_path, capsys):
    (tmp_path / "candidate").mkdir()
    (tmp_path / "candidate" / "profile.yaml").write_text("personal: {}\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "--lang", "en", "validate"]) == 1
    out = capsys.readouterr().out
    assert "ERROR" in out and "personal.name is required." in out
    assert main(["--root", str(tmp_path), "--lang", "es", "validate"]) == 1
    assert "personal.name es obligatorio." in capsys.readouterr().out


def test_cli_rejects_unsupported_language(tmp_path):
    with pytest.raises(SystemExit):
        main(["--root", str(tmp_path), "--lang", "xx", "validate"])


def test_no_hardcoded_spanish_left_in_migrated_validate():
    from pathlib import Path
    source = Path(i18n.__file__).with_name("profile.py").read_text(encoding="utf-8")
    block = source[source.index("def validate"):]
    assert not re.search(r"(obligatorio|no tiene id|duplicados|inexistente)", block)
