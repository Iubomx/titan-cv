"""Gestión de Chrome del perfil del robot en cualquier SO (psutil simulado: no se cierra ningún proceso real)."""
import psutil

from cvtitan.apply import human_browser as hb


class FakeProc:
    def __init__(self, pid, name, cmdline, ppid=500):
        self.info = {"pid": pid, "name": name, "cmdline": cmdline, "ppid": ppid}
        self.killed = False

    def children(self, recursive=True):
        return []

    def kill(self):
        self.killed = True


def _patch(monkeypatch, procs):
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter(procs))


def test_profile_procs_matches_only_main_chrome_of_this_profile(monkeypatch, tmp_path):
    profile = tmp_path / "browser-profile"
    other = tmp_path / "other-profile"
    mine = FakeProc(1, "chrome.exe", ["chrome", f"--user-data-dir={profile}"])
    child = FakeProc(2, "chrome.exe", ["chrome", f"--user-data-dir={profile}", "--type=renderer"])
    foreign = FakeProc(3, "chrome", ["chrome", f"--user-data-dir={other}"])
    not_chrome = FakeProc(4, "python", ["python", f"--user-data-dir={profile}"])
    _patch(monkeypatch, [mine, child, foreign, not_chrome])
    assert hb._profile_procs(profile) == [mine]


def test_profile_procs_handles_quoted_path_and_chromium(monkeypatch, tmp_path):
    profile = tmp_path / "browser-profile"
    proc = FakeProc(1, "Chromium", ["chromium", f'--user-data-dir="{profile}"'])
    _patch(monkeypatch, [proc])
    assert hb._profile_procs(profile) == [proc]


def test_release_profile_returns_zero_when_nothing_runs(monkeypatch, tmp_path):
    _patch(monkeypatch, [])
    assert hb.release_profile(tmp_path / "p", grace_s=1) == 0


def test_release_profile_kills_leftover_after_grace(monkeypatch, tmp_path):
    profile = tmp_path / "p"
    proc = FakeProc(1, "chrome", ["chrome", f"--user-data-dir={profile}"])
    _patch(monkeypatch, [proc])
    monkeypatch.setattr("time.sleep", lambda *_: None)
    assert hb.release_profile(profile, grace_s=2) == 1
    assert proc.killed


def test_posix_orphans_only_headless_with_dead_parent(monkeypatch, tmp_path):
    profile = tmp_path / "p"
    base = ["chrome", f"--user-data-dir={profile}"]
    headless_orphan = FakeProc(1, "chrome", base + ["--headless=new"], ppid=1)
    headless_alive = FakeProc(2, "chrome", base + ["--headless=new"], ppid=4242)
    windowed = FakeProc(3, "chrome", base, ppid=1)
    _patch(monkeypatch, [headless_orphan, headless_alive, windowed])
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: pid == 4242)
    assert hb._release_orphans_posix(profile) == 1
    assert headless_orphan.killed and not headless_alive.killed and not windowed.killed


def test_find_chrome_falls_back_to_chromium_on_path(monkeypatch):
    monkeypatch.setattr(hb, "CANDIDATES", [])
    monkeypatch.setattr(hb.shutil, "which", lambda name: "/usr/bin/chromium" if name == "chromium" else None)
    assert hb.find_chrome() == "/usr/bin/chromium"
