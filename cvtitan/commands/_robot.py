"""Bloqueo del navegador del robot y prioridad baja del proceso (compartidos por los comandos que lo usan)."""
from __future__ import annotations

import os
import sys

from ..utils import Workspace
from ._common import CliError


class RobotLock:
    """Un solo proceso a la vez usa el navegador del robot (data/robot.lock con el PID y el comando)."""

    def __init__(self, ws: Workspace, what: str):
        self.path = ws.root / "data" / "robot.lock"
        self.what = what

    @staticmethod
    def _alive(pid: int) -> bool:
        if sys.platform == "win32":
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return code.value == 259                                          # STILL_ACTIVE
        try:
            import os
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def __enter__(self):
        import os
        if self.path.exists():
            try:
                pid, what = self.path.read_text(encoding="utf-8").split("|", 1)
                if int(pid) != os.getpid() and self._alive(int(pid)):
                    raise CliError(f"Another CV TITAN process is using the robot browser: «{what}» "
                                   f"(PID {pid}). Wait for it to finish or close it and try again.")
            except ValueError:
                pass
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(f"{os.getpid()}|{self.what}", encoding="utf-8")
        return self

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except OSError:
            pass
        return False


def _quiet_process() -> None:
    """Prioridad baja para este proceso y sus Chrome: no compite con lo que estés haciendo."""
    if sys.platform != "win32":
        try:
            os.nice(5)
        except (AttributeError, OSError):
            pass
        return
    if sys.platform == "win32":
        try:
            import ctypes
            BELOW_NORMAL = 0x4000
            k32 = ctypes.windll.kernel32
            k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL)
        except Exception:
            pass
