"""Cofre con passphrase: ida y vuelta, passphrase incorrecta, conflictos y rutas inseguras (datos ficticios)."""
import json

import pytest

from cvtitan import vault
from cvtitan.cli import main

N = 2 ** 10                                           # scrypt barato: solo para las pruebas
SECRET = "zoe.quispe@example.com"


@pytest.fixture
def root(tmp_path):
    (tmp_path / "candidate" / "documents").mkdir(parents=True)
    (tmp_path / "candidate" / "profile.yaml").write_text(f"personal: {{email: {SECRET}}}\n", encoding="utf-8")
    (tmp_path / "candidate" / "profile.example.yaml").write_text("personal: {name: Ejemplo}\n", encoding="utf-8")
    (tmp_path / "candidate" / "documents" / "cv.pdf").write_bytes(b"%PDF fake " + SECRET.encode())
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-test\n", encoding="utf-8")
    (tmp_path / "data" / "outputs" / "job1").mkdir(parents=True)
    (tmp_path / "data" / "outputs" / "job1" / "cv.md").write_text("# CV Zoe", encoding="utf-8")
    (tmp_path / "data" / "cvtitan.db").write_bytes(b"SQLite format 3\x00" + b"\x01" * 64)
    (tmp_path / "data" / "browser-profile").mkdir()
    (tmp_path / "data" / "browser-profile" / "Cookies").write_text("keep", encoding="utf-8")
    return tmp_path


def test_collect_picks_sensitive_files_and_skips_templates_and_browser_profile(root):
    rels = vault.collect(root)
    assert "candidate/profile.yaml" in rels and "candidate/documents/cv.pdf" in rels and ".env" in rels
    assert "data/cvtitan.db" in rels and "data/outputs/job1/cv.md" in rels
    assert "candidate/profile.example.yaml" not in rels and not any("browser-profile" in r for r in rels)


def test_lock_removes_plaintext_and_vault_has_no_plaintext(root):
    original_db = (root / "data" / "cvtitan.db").read_bytes()
    count = vault.lock(root, "correct horse", scrypt_n=N)
    assert count == 5 and vault.is_locked(root)
    assert not (root / "candidate" / "profile.yaml").exists() and not (root / ".env").exists()
    assert not (root / "data" / "outputs").exists()
    assert (root / "candidate" / "profile.example.yaml").exists()          # la plantilla pública no se toca
    assert (root / "data" / "browser-profile" / "Cookies").exists()
    blob = vault.vault_path(root).read_text(encoding="utf-8")
    assert SECRET not in blob and "sk-test" not in blob and original_db.hex()[:20] not in blob


def test_round_trip_restores_identical_files(root):
    before = {rel: (root / rel).read_bytes() for rel in vault.collect(root)}
    vault.lock(root, "correct horse", scrypt_n=N)
    assert vault.unlock(root, "correct horse") == len(before)
    assert {rel: (root / rel).read_bytes() for rel in before} == before
    assert not vault.is_locked(root)


def test_wrong_passphrase_changes_nothing(root):
    vault.lock(root, "correct horse", scrypt_n=N)
    with pytest.raises(vault.VaultError, match="incorrecta"):
        vault.unlock(root, "wrong")
    assert vault.is_locked(root) and not (root / "candidate" / "profile.yaml").exists()


def test_empty_passphrase_and_double_lock_are_rejected(root):
    with pytest.raises(vault.VaultError):
        vault.lock(root, "", scrypt_n=N)
    assert (root / ".env").exists()
    vault.lock(root, "pw", scrypt_n=N)
    with pytest.raises(vault.VaultError, match="Ya está bloqueado"):
        vault.lock(root, "pw", scrypt_n=N)


def test_lock_without_data_is_rejected(tmp_path):
    with pytest.raises(vault.VaultError, match="No hay datos"):
        vault.lock(tmp_path, "pw", scrypt_n=N)


def test_unlock_refuses_to_overwrite_unless_forced(root):
    vault.lock(root, "pw", scrypt_n=N)
    (root / ".env").write_text("NEW=1\n", encoding="utf-8")
    with pytest.raises(vault.VaultError, match="sobrescribir"):
        vault.unlock(root, "pw")
    assert vault.is_locked(root) and (root / ".env").read_text(encoding="utf-8") == "NEW=1\n"
    vault.unlock(root, "pw", force=True)
    assert (root / ".env").read_text(encoding="utf-8") == "ANTHROPIC_API_KEY=sk-test\n"


def test_tampered_vault_is_detected_and_not_restored(root):
    vault.lock(root, "pw", scrypt_n=N)
    path = vault.vault_path(root)
    doc = json.loads(path.read_text(encoding="utf-8"))
    entry = next(iter(doc["files"].values()))
    entry["token"] = entry["token"][:-6] + "AAAAAA"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(vault.VaultError):
        vault.unlock(root, "pw")
    assert not (root / "candidate" / "profile.yaml").exists()


def test_path_traversal_entries_are_rejected(root):
    vault.lock(root, "pw", scrypt_n=N)
    path = vault.vault_path(root)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["files"]["../escape.txt"] = doc["files"].pop(next(iter(doc["files"])))
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(vault.VaultError):
        vault.unlock(root, "pw")
    assert not (root.parent / "escape.txt").exists()


def test_status(root):
    assert vault.status(root) == {"locked": False, "plain_files": 5}
    vault.lock(root, "pw", scrypt_n=N)
    st = vault.status(root)
    assert st["locked"] is True and st["files"] == 5


def test_cli_lock_unlock_with_env_passphrase(root, monkeypatch, capsys):
    monkeypatch.setenv("CVTITAN_VAULT_PASSPHRASE", "cli passphrase")
    assert main(["--root", str(root), "vault", "status"]) == 0
    assert main(["--root", str(root), "vault", "lock"]) == 0
    assert vault.is_locked(root)
    assert main(["--root", str(root), "vault", "status"]) == 0
    assert "LOCKED" in capsys.readouterr().out
    monkeypatch.setenv("CVTITAN_VAULT_PASSPHRASE", "wrong")
    assert main(["--root", str(root), "vault", "unlock"]) == 2
    monkeypatch.setenv("CVTITAN_VAULT_PASSPHRASE", "cli passphrase")
    assert main(["--root", str(root), "vault", "unlock"]) == 0
    assert (root / "candidate" / "profile.yaml").exists() and not vault.is_locked(root)
