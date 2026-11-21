"""`cvtitan vault lock|unlock|status`: cifrado en reposo con passphrase (ver `cvtitan/vault.py`)."""
from __future__ import annotations

import getpass
import os

from .. import vault
from ..utils import Workspace
from ._common import CliError

ENV_VAR = "CVTITAN_VAULT_PASSPHRASE"


def register(sub) -> None:
    s = sub.add_parser("vault", help="Encrypt your personal data at rest with a passphrase (lock/unlock/status).")
    s.add_argument("action", choices=["lock", "unlock", "status"])
    s.add_argument("--force", action="store_true", help="With unlock: overwrite existing plaintext files.")
    s.set_defaults(func=run)


def _passphrase(confirm: bool) -> str:
    env = os.environ.get(ENV_VAR)
    if env:
        return env                         # para automatizar; menos seguro que la entrada interactiva
    first = getpass.getpass("Passphrase: ")
    if confirm and getpass.getpass("Repeat passphrase: ") != first:
        raise CliError("The passphrases do not match. Nothing was changed.")
    return first


def run(args) -> int:
    root = Workspace.resolve(args.root).root
    try:
        if args.action == "status":
            st = vault.status(root)
            if st["locked"]:
                print(f"LOCKED: {st['files']} encrypted file(s) in {vault.VAULT_NAME}.")
            else:
                print(f"Unlocked: {st['plain_files']} file(s) would be encrypted by `cvtitan vault lock`.")
            return 0
        if args.action == "lock":
            print("Close TITAN, the web app and Chrome first. If you forget the passphrase, your data CANNOT be recovered.")
            n = vault.lock(root, _passphrase(confirm=True))
            print(f"Locked: {n} file(s) encrypted into {vault.VAULT_NAME}; plaintext copies removed after verification.")
            return 0
        n = vault.unlock(root, _passphrase(confirm=False), force=args.force)
        print(f"Unlocked: {n} file(s) restored.")
        return 0
    except vault.VaultError as exc:
        raise CliError(str(exc)) from exc
