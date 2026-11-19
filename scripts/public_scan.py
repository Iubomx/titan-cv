"""Control de seguridad del repositorio público (lo ejecuta GitHub Actions en cada cambio).

Falla (código 1) si encuentra en archivos versionados:
  - secretos: claves de API, tokens de GitHub/AWS/Slack, llaves privadas, contraseñas en texto;
  - archivos que nunca deben publicarse: perfiles reales, CV, bases de datos, registros, sesiones, .env;
  - rutas locales de un usuario (C:\\Users\\<nombre>\\..., /home/<nombre>/...);
  - correos que no sean de ejemplo (@example.com, noreply);
  - caracteres de control en código o configuración.
El informe nunca muestra el valor detectado: solo archivo, línea y categoría.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import PurePosixPath

SECRETS = {
    "anthropic key": r"sk-ant-[A-Za-z0-9_\-]{20,}",
    "github token": r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}",
    "aws key": r"AKIA[0-9A-Z]{16}",
    "slack token": r"xox[abprs]-[A-Za-z0-9-]{10,}",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "password literal": r"(?i)(password|passwd|contrase(n|ñ)a)\s*[:=]\s*['\"][^'\"\s]{6,}['\"]",
}
FORBIDDEN = [r"^candidate/(?!.*\.example\.yaml$).+", r"^data/", r"(^|/)\.env$", r"\.(db|sqlite|pdf|docx|log)$",
             r"browser-profile", r"(^|/)answers\.yaml$"]
LOCAL_PATH = r"(?i)[a-z]:\\\\?users\\\\?(?!<|\{|%|public\b|default\b|runneradmin\b)[a-z0-9._-]+\\\\|/home/(?!runner\b|user\b|<)[a-z0-9._-]+/"
EMAIL = r"[\w.+-]+@(?!example\.(com|org)|users\.noreply\.github\.com|anthropic\.com|b\.c\b|x\.cl\b)[\w-]+(\.[\w-]+)+"
TEXT_EXT = {".py", ".md", ".yaml", ".yml", ".json", ".toml", ".txt", ".cmd", ".bat", ".ps1", ".html", ".cfg", ".ini", ""}


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f]


def scan(files: list[str]) -> list[tuple[str, int, str]]:
    findings = []
    for f in files:
        for rx in FORBIDDEN:
            if re.search(rx, f):
                findings.append((f, 0, "forbidden file"))
        if PurePosixPath(f).suffix.lower() not in TEXT_EXT:
            continue
        try:
            data = open(f, "rb").read()
        except OSError:
            continue
        if f.endswith((".py", ".yaml", ".yml", ".json", ".toml")) and any(b in data for b in (b"\x00", b"\x08", b"\x1b")):
            findings.append((f, 0, "control character"))
        text = data.decode("utf-8", errors="ignore")
        if f == "scripts/public_scan.py":
            continue                                     # este archivo contiene los patrones
        checks = {**SECRETS, "local user path": LOCAL_PATH, "real email": EMAIL}
        for name, rx in checks.items():
            for m in re.finditer(rx, text):
                findings.append((f, text[:m.start()].count("\n") + 1, name))
    return findings


def main() -> int:
    findings = scan(tracked_files())
    for f, line, cat in findings:
        print(f"FAIL {cat:<18} {f}:{line}")
    print(f"public_scan: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
