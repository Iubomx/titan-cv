"""Cifrado en reposo con passphrase: `titan vault lock` guarda tus datos personales en un solo archivo cifrado.

Qué cifra (si existen): `candidate/*.yaml` (menos las plantillas `*.example.yaml`), `candidate/documents/`, `.env`,
`data/cvtitan.db` y `data/auto/refs.json`, y `data/outputs/` (CV generados). NO toca `data/browser-profile/` (Chrome
lo usa y puede estar abierto): protege esa carpeta con el cifrado de disco de tu sistema.

Seguridad: Fernet (AES-128-CBC + HMAC) con clave derivada por scrypt de tu passphrase. Antes de borrar nada en claro,
`lock` descifra todo y compara el hash de cada archivo; `unlock` verifica la passphrase y los hashes antes de escribir.
**Si olvidas la passphrase, los datos NO se pueden recuperar.** Requiere `pip install -e ".[vault]"`.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

VAULT_NAME = "vault.titanvault"
VERSION = 1
CHECK_TEXT = b"titan-vault"
SCRYPT_N = 2 ** 15
INCLUDE_FILES = (".env", "data/cvtitan.db", "data/cvtitan.db-wal", "data/cvtitan.db-shm", "data/auto/refs.json")
INCLUDE_DIRS = ("candidate/documents", "data/outputs")


class VaultError(Exception):
    """Error esperado del cofre (passphrase incorrecta, ya bloqueado, conflicto...). Nunca deja datos a medias."""


def _crypto():
    try:
        from cryptography.fernet import Fernet, InvalidToken
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError as exc:
        raise VaultError('Falta el paquete "cryptography". Instálalo con: pip install -e ".[vault]"') from exc
    return Fernet, InvalidToken, Scrypt


def vault_path(root: Path) -> Path:
    return root / VAULT_NAME


def _key(passphrase: str, salt: bytes, n: int) -> bytes:
    _, _, Scrypt = _crypto()
    return base64.urlsafe_b64encode(Scrypt(salt=salt, length=32, n=n, r=8, p=1).derive(passphrase.encode("utf-8")))


def collect(root: Path) -> list[str]:
    """Rutas relativas (con `/`) de los archivos a cifrar que existen hoy."""
    found: list[str] = []
    cand = root / "candidate"
    if cand.is_dir():
        found += [f"candidate/{p.name}" for p in sorted(cand.glob("*.yaml")) if not p.name.endswith(".example.yaml")]
    found += [rel for rel in INCLUDE_FILES if (root / rel).is_file()]
    for d in INCLUDE_DIRS:
        base = root / d
        if base.is_dir():
            found += [p.relative_to(root).as_posix() for p in sorted(base.rglob("*")) if p.is_file()]
    return list(dict.fromkeys(found))


def _safe_target(root: Path, rel: str) -> Path:
    target = (root / rel).resolve()
    if root.resolve() not in target.parents:
        raise VaultError(f"Ruta insegura en el cofre: {rel}")
    return target


def is_locked(root: Path) -> bool:
    return vault_path(root).exists()


def status(root: Path) -> dict:
    if not is_locked(root):
        return {"locked": False, "plain_files": len(collect(root))}
    data = json.loads(vault_path(root).read_text(encoding="utf-8"))
    return {"locked": True, "files": len(data.get("files", {})), "version": data.get("version")}


def lock(root: Path, passphrase: str, scrypt_n: int = SCRYPT_N) -> int:
    """Cifra los archivos sensibles y borra los originales SOLO tras verificar que se descifran idénticos."""
    Fernet, _, _ = _crypto()
    if not passphrase:
        raise VaultError("La passphrase no puede estar vacía.")
    if is_locked(root):
        raise VaultError("Ya está bloqueado (existe el cofre). Ejecuta `vault unlock` primero.")
    rels = collect(root)
    if not rels:
        raise VaultError("No hay datos que cifrar.")
    salt = os.urandom(16)
    f = Fernet(_key(passphrase, salt, scrypt_n))
    files: dict[str, dict] = {}
    for rel in rels:
        raw = (root / rel).read_bytes()
        files[rel] = {"token": f.encrypt(raw).decode("ascii"), "sha256": hashlib.sha256(raw).hexdigest()}
    doc = {"version": VERSION, "kdf": {"name": "scrypt", "n": scrypt_n, "r": 8, "p": 1,
                                       "salt": base64.b64encode(salt).decode("ascii")},
           "check": f.encrypt(CHECK_TEXT).decode("ascii"), "files": files}
    tmp = vault_path(root).with_suffix(".tmp")
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    try:
        _decrypt_all(json.loads(tmp.read_text(encoding="utf-8")), passphrase)      # verificación completa
    except VaultError:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(vault_path(root))
    for rel in rels:
        (root / rel).unlink()
    for d in INCLUDE_DIRS:                                  # carpetas vacías que quedaron
        base = root / d
        if base.is_dir():
            for sub in sorted((p for p in base.rglob("*") if p.is_dir()), reverse=True) + [base]:
                try:
                    sub.rmdir()
                except OSError:
                    pass
    return len(rels)


def _decrypt_all(doc: dict, passphrase: str) -> dict[str, bytes]:
    Fernet, InvalidToken, _ = _crypto()
    try:
        kdf = doc["kdf"]
        f = Fernet(_key(passphrase, base64.b64decode(kdf["salt"]), int(kdf["n"])))
        if f.decrypt(doc["check"].encode("ascii")) != CHECK_TEXT:
            raise VaultError("Passphrase incorrecta.")
        out: dict[str, bytes] = {}
        for rel, entry in doc["files"].items():
            raw = f.decrypt(entry["token"].encode("ascii"))
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise VaultError(f"El archivo '{rel}' no coincide con su hash: cofre dañado.")
            out[rel] = raw
        return out
    except InvalidToken as exc:
        raise VaultError("Passphrase incorrecta o cofre dañado.") from exc
    except (KeyError, ValueError, TypeError) as exc:
        raise VaultError("Formato de cofre no válido.") from exc


def unlock(root: Path, passphrase: str, force: bool = False) -> int:
    """Restaura los archivos. No escribe nada si la passphrase es incorrecta o si habría conflictos."""
    if not is_locked(root):
        raise VaultError("No hay cofre: nada que desbloquear.")
    doc = json.loads(vault_path(root).read_text(encoding="utf-8"))
    contents = _decrypt_all(doc, passphrase)                 # falla aquí antes de tocar el disco
    targets = {rel: _safe_target(root, rel) for rel in contents}
    conflicts = [rel for rel, path in targets.items() if path.exists()]
    if conflicts and not force:
        raise VaultError("Ya existen archivos que se sobrescribirían: " + ", ".join(conflicts[:5])
                         + ". Muévelos o usa --force.")
    for rel, raw in contents.items():
        targets[rel].parent.mkdir(parents=True, exist_ok=True)
        targets[rel].write_bytes(raw)
    for rel, raw in contents.items():                        # verificación final antes de borrar el cofre
        if hashlib.sha256(targets[rel].read_bytes()).hexdigest() != doc["files"][rel]["sha256"]:
            raise VaultError(f"No se pudo restaurar '{rel}' correctamente; el cofre se conserva.")
    vault_path(root).unlink()
    return len(contents)
