"""Chrome normal (sin automatización) sobre el perfil del robot, para que la persona inicie sesión.

Google y otros proveedores bloquean el inicio de sesión dentro de navegadores controlados por programas
(«Es posible que este navegador o la app no sean seguros»). Por eso los logins se hacen en un Chrome
común, abierto con el mismo perfil (data/browser-profile): la sesión queda guardada ahí y el robot la
reutiliza después. El robot no ve ni escribe contraseñas.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_chrome() -> str | None:
    for c in CANDIDATES:
        if c and Path(c).exists():
            return c
    return shutil.which("chrome") or shutil.which("google-chrome")


def open_for_login(profile_dir: Path, urls: list[str]) -> subprocess.Popen:
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("No encontré Google Chrome instalado.")
    profile_dir.mkdir(parents=True, exist_ok=True)
    args = [chrome, f"--user-data-dir={profile_dir}", "--no-first-run", "--no-default-browser-check",
            "--disable-background-mode", "--new-window", *urls]
    return subprocess.Popen(args)


def _ps_like(path: Path) -> str:
    """Escapa una ruta para usarla dentro de un literal '...' de PowerShell con el operador -like:
    duplica los apóstrofes y neutraliza los comodines (* ? [ ])."""
    out = str(path).replace("'", "''")
    for ch in "*?[]":
        out = out.replace(ch, "`" + ch)
    return out


def release_profile(profile_dir: Path, grace_s: int = 8) -> int:
    """Cierra procesos de Chrome que sigan usando el perfil del robot sin ventana (modo en segundo plano).
    Devuelve cuántos quedaban. Solo toca procesos cuyo --user-data-dir es ESTE perfil."""
    if os.name != "nt":
        return 0
    import time
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { $_.CommandLine -like "
          f"'*{_ps_like(profile_dir)}*' -and $_.CommandLine -notlike '*--type=*' }} | ForEach-Object {{ $_.ProcessId }}")
    for _ in range(grace_s):
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout
        pids = [x.strip() for x in out.split() if x.strip().isdigit()]
        if not pids:
            return 0
        time.sleep(1)
    for pid in pids:
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
    return len(pids)


def wait_closed(proc: subprocess.Popen, timeout: int | None = None, profile_dir: Path | None = None) -> bool:
    """True si la persona cerró la ventana de Chrome dentro del plazo. Luego libera el perfil del robot."""
    try:
        proc.wait(timeout=timeout)
        if profile_dir:
            release_profile(profile_dir)
        return True
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        return False



def release_orphans(profile_dir: Path) -> int:
    """Cierra Chrome HUÉRFANOS del perfil del robot: sin ventana visible y cuyo proceso padre ya no existe
    (restos de ejecuciones anteriores). Nunca toca un Chrome con ventana abierta."""
    if os.name != "nt":
        return 0
    ps = (
        "$ids = @(Get-Process | ForEach-Object { $_.Id }); "
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { $_.CommandLine -like "
        f"'*{_ps_like(profile_dir)}*' -and $_.CommandLine -notlike '*--type=*' }} | ForEach-Object {{ "
        "$p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue; "
        "if ($p -and -not $p.MainWindowTitle -and ($ids -notcontains $_.ParentProcessId)) { $_.ProcessId } }"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout
    pids = [x.strip() for x in out.split() if x.strip().isdigit()]
    for pid in pids:
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
    return len(pids)
