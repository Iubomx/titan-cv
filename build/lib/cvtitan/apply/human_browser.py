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
    for name in ("google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


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


def _same_path(a: str, b: Path) -> bool:
    return os.path.normcase(os.path.realpath(a.strip('"'))) == os.path.normcase(os.path.realpath(str(b)))


def _profile_procs(profile_dir: Path) -> list:
    """Procesos principales de Chrome/Chromium (no los hijos `--type=`) cuyo --user-data-dir es ESTE perfil."""
    import psutil
    found = []
    for proc in psutil.process_iter(["pid", "ppid", "name", "cmdline"]):
        info = proc.info
        name = (info.get("name") or "").lower()
        args = info.get("cmdline") or []
        if "chrom" not in name or any(a.startswith("--type=") for a in args):
            continue
        for a in args:
            if a.startswith("--user-data-dir=") and _same_path(a.split("=", 1)[1], profile_dir):
                found.append(proc)
                break
    return found


def _kill_tree(proc) -> None:
    import psutil
    try:
        victims = proc.children(recursive=True) + [proc]
    except psutil.Error:
        victims = [proc]
    for victim in victims:
        try:
            victim.kill()
        except psutil.Error:
            pass


def release_profile(profile_dir: Path, grace_s: int = 8) -> int:
    """Cierra procesos de Chrome que sigan usando el perfil del robot sin ventana (modo en segundo plano).
    Devuelve cuántos quedaban. Solo toca procesos cuyo --user-data-dir es ESTE perfil. Funciona en Windows,
    macOS y Linux (psutil)."""
    import time
    procs: list = []
    for _ in range(grace_s):
        procs = _profile_procs(profile_dir)
        if not procs:
            return 0
        time.sleep(1)
    for proc in procs:
        _kill_tree(proc)
    return len(procs)


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
        return _release_orphans_posix(profile_dir)
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


def _release_orphans_posix(profile_dir: Path) -> int:
    """macOS/Linux: sin API de ventanas, solo se cierran los Chrome HEADLESS del perfil cuyo padre ya no existe.
    Un Chrome con ventana nunca se toca."""
    import psutil
    killed = 0
    for proc in _profile_procs(profile_dir):
        args = proc.info.get("cmdline") or []
        ppid = proc.info.get("ppid")
        if any(a.startswith("--headless") for a in args) and (ppid in (0, 1) or not psutil.pid_exists(ppid)):
            _kill_tree(proc)
            killed += 1
    return killed
