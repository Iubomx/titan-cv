"""Prueba de fuga: los datos del perfil no salen por la terminal ni por los archivos de informe (datos ficticios)."""
import csv

import pytest

from cvtitan import privacy
from cvtitan.cli import main
from cvtitan.db import DB
from cvtitan.funnel import write
from cvtitan.utils import dump_yaml

SECRETS = ["zoe.quispe@example.com", "Zoe Quispe Ejemplo", "Quispe", "+51 999 111 222", "Arequipa"]


@pytest.fixture
def root(tmp_path):
    dump_yaml({"personal": {"name": "Zoe Quispe Ejemplo", "first_name": "Zoe", "last_name": "Quispe Ejemplo",
                            "email": "zoe.quispe@example.com", "phone": "+51 999 111 222",
                            "location": "Arequipa, Perú"}}, tmp_path / "candidate" / "profile.yaml")
    db = DB(tmp_path / "data" / "cvtitan.db")
    db.upsert("j1", company="Consultora de zoe.quispe@example.com", title="Rol para Zoe Quispe Ejemplo",
              url="https://jobs.example.com/ofertas/zoe-quispe-123")
    db.set_status("j1", "applied")
    db.add_process_event("j1", "followup", "2099-01-01", "Llamar al +51 999 111 222 (Arequipa)")
    db.close()
    yield str(tmp_path)
    privacy.configure(None)


def _assert_clean(text):
    for secret in SECRETS:
        assert secret not in text, f"se filtró: {secret}"
    assert "zoe-quispe-123" not in text                       # la URL real tampoco se muestra


@pytest.mark.parametrize("args", [["informe", "--historial"], ["informe", "--semana"],
                                  ["track", "agenda", "--days", "36500"]])
def test_terminal_output_never_contains_profile_data(root, capsys, args):
    assert main(["--root", root, *args]) == 0
    out = capsys.readouterr().out
    assert out.strip()                                        # sí imprimió algo
    _assert_clean(out)


def test_history_still_shows_masked_placeholders(root, capsys):
    main(["--root", root, "informe", "--historial"])
    out = capsys.readouterr().out
    assert "[NAME]" in out and "jobs.example.com #JOB-" in out


def test_funnel_csv_never_contains_profile_data(root, tmp_path):
    privacy.configure(tmp_path / "candidate" / "profile.yaml")
    out = tmp_path / "f.csv"
    write([{"line": "A", "tier": "no", "reason": "Hola Zoe Quispe Ejemplo, escribe a zoe.quispe@example.com",
            "title": "Rol en Arequipa", "company": "Zoe Quispe Ejemplo SpA",
            "url": "https://jobs.example.com/ofertas/zoe-quispe-123"}], out, tmp_path / "refs.json")
    text = out.read_text(encoding="utf-8-sig")
    _assert_clean(text)
    assert list(csv.DictReader(text.splitlines(), delimiter=";"))[0]["ref"].startswith("jobs.example.com #JOB-")
