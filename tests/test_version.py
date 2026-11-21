"""La versión del paquete debe ser una sola: pyproject.toml y cvtitan.__version__ no pueden divergir."""
import re
from pathlib import Path

import cvtitan

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_and_package_versions_agree():
    declared = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    assert cvtitan.__version__ == declared


def test_changelog_has_an_entry_for_the_current_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{cvtitan.__version__}]" in changelog
