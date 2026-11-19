"""Publicación segura de la versión open source (`cvtitan publish`).

El repositorio privado es la fuente principal; el público es una DISTRIBUCIÓN SANEADA, generada así:
  1. copia temporal del último commit del privado (`git archive HEAD`: solo lo versionado, nada sin confirmar);
  2. exporta SOLO lo que está en la lista blanca de publish/manifest.yaml;
  3. superpone publish/public/ (README, LICENSE, plantillas, CI) y sanea la configuración personal;
  4. audita: archivos prohibidos, secretos, datos personales (leídos de TU candidate/profile.yaml local, nunca
     escritos en el código), rutas locales, caracteres de control y el historial del repositorio público;
  5. ejecuta las pruebas sobre la copia exportada;
  6. valida una instalación desde cero (init + validate + .gitignore protege los archivos personales);
  7. escribe un informe que nunca reproduce el valor detectado (solo archivo, línea y categoría);
  8. BLOQUEA ante cualquier hallazgo o falla, sin opción para omitir comprobaciones;
  9. publica (commit + push al repositorio público) solo con --push y una aprobación escrita en la terminal.
"""
from __future__ import annotations

import fnmatch
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .utils import load_yaml

TEXT_EXT = {".py", ".md", ".yaml", ".yml", ".json", ".toml", ".txt", ".cmd", ".bat", ".ps1", ".html", ".cfg", ""}
SECRETS = {
    "anthropic key": r"sk-ant-[A-Za-z0-9_\-]{20,}",
    "github token": r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}",
    "aws key": r"AKIA[0-9A-Z]{16}",
    "slack token": r"xox[abprs]-[A-Za-z0-9-]{10,}",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "password literal": r"(?i)(password|passwd|contrase(n|ñ)a)\s*[:=]\s*['\"][^'\"\s]{6,}['\"]",
}
FORBIDDEN = [r"^candidate/(?!.*\.example\.yaml$).+", r"^data/", r"(^|/)\.env$", r"\.(db|sqlite|pdf|docx|log)$",
             r"browser-profile", r"(^|/)answers\.yaml$", r"^docs/auditoria/"]
TEMPLATE_P1 = ["data_bi", "backend", "fullstack", "automation_integration"]
TEMPLATE_P2 = ["frontend", "ai_ml_llm", "it_support", "it_engineering", "cloud_devops", "qa_testing",
               "infrastructure_networks"]
FREEFORM_KEYS = {"include", "groups", "countries", "companies", "roles", "technologies"}   # contenido libre
GENERIC_WORDS = {"minera", "mining", "international", "chile", "proyecto", "plataforma", "sistema", "ingeniero",
                 "ingenieria", "datos", "operaciones", "despacho", "analista", "central", "controller", "operador"}


@dataclass
class Finding:
    category: str
    path: str
    line: int = 0

    def __str__(self) -> str:
        return f"{self.category:<24} {self.path}{':' + str(self.line) if self.line else ''}"


@dataclass
class Result:
    export_dir: Path
    files: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    steps: list[tuple[str, bool, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings and all(ok for _, ok, _ in self.steps)


# ------------------------------------------------------------------ 1-3. exportar y sanear
def load_manifest(root: Path) -> dict:
    return load_yaml(root / "publish" / "manifest.yaml")


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, p) or path == p for p in patterns)


def export(root: Path, manifest: dict, dest: Path) -> list[str]:
    """Último commit del privado -> dest, solo lista blanca; luego overlay y saneadores."""
    archive = subprocess.run(["git", "-C", str(root), "archive", "--format=tar", "HEAD"], capture_output=True,
                             check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        members = [m for m in tar.getmembers() if m.isfile()
                   and _matches(m.name, manifest["include"]) and not _matches(m.name, manifest.get("exclude", []))]
        tar.extractall(dest, members=members, filter="data")
    overlay = root / manifest.get("overlay", "publish/public")
    if overlay.exists():
        for src in overlay.rglob("*"):
            if src.is_file() and "__pycache__" not in src.parts and src.suffix != ".pyc":
                target = dest / src.relative_to(overlay)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
    sanitize_config(dest)
    return sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())


def sanitize_config(dest: Path) -> None:
    """Configuración personal -> valores neutros y comentados (el código no cambia)."""
    auto = dest / "config" / "auto.yaml"
    if auto.exists() and not auto.read_text(encoding="utf-8").startswith("# PLANTILLA"):
        lines = auto.read_text(encoding="utf-8").splitlines()
        body = lines[next((i for i, ln in enumerate(lines) if ln.strip() and not ln.startswith("#")), 0):]
        header = ["# Reglas de la Línea A (portales locales). Piloto automático (`cvtitan auto`): busca, filtra y, SOLO si",
                  "# activas lines.A.send_enabled en config/lines.yaml, postula a las vacantes que cumplan TODAS estas",
                  "# reglas. Edita con cuidado: cada envío es real. Tu pretensión se define en candidate/profile.yaml.", ""]
        auto.write_text("\n".join(header + body) + "\n", encoding="utf-8")
    lines_cfg = dest / "config" / "lines.yaml"
    if lines_cfg.exists():
        s = lines_cfg.read_text(encoding="utf-8")
        s = re.sub(r"(?m)^(\s*send_enabled:\s*)true\b.*$",
                   r"\1false          # true SOLO cuando hayas revisado tus reglas: cada envío es real", s)
        s = re.sub(r"(?m)^(\s*min_monthly:\s*)\d+.*$", r"\g<1>0              # tu mínimo mensual (USD); 0 = no filtrar", s)
        s = re.sub(r"(?m)^(\s*target_monthly:\s*)\d+.*$", r"\g<1>4000           # desde aquí, puntaje completo de sueldo", s)
        lines_cfg.write_text(s, encoding="utf-8")
    jd = dest / "config" / "job_dictionary.json"
    if jd.exists():
        data = json.loads(jd.read_text(encoding="utf-8"))
        data.pop("profile_signals", None)
        roles = list(data.get("roles") or {})
        if roles:                                        # prioridades de ejemplo, no las del candidato
            p1 = [r for r in TEMPLATE_P1 if r in roles]
            p2 = [r for r in TEMPLATE_P2 if r in roles]
            data["priority"] = {"P1": p1, "P2": p2, "P3": [r for r in roles if r not in p1 + p2]}
        jd.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ 4. auditoría
def _accent_free(word: str) -> str:
    base = "".join(c for c in unicodedata.normalize("NFD", word.lower()) if unicodedata.category(c) != "Mn")
    table = {"a": "[aáàä]", "e": "[eéèë]", "i": "[iíìï]", "o": "[oóòö]", "u": "[uúùü]", "n": "[nñ]"}
    return "".join(table.get(c, re.escape(c)) for c in base)


def personal_patterns(root: Path) -> dict[str, re.Pattern]:
    """Patrones de TUS datos, construidos en memoria desde tu perfil local (nunca se escriben en el código)."""
    pats: dict[str, list[str]] = {"personal: name": [], "personal: contact": [], "personal: location": [],
                                  "personal: employer/project": [], "personal: salary": [], "local path": []}
    prof_path = root / "candidate" / "profile.yaml"
    prof = load_yaml(prof_path) if prof_path.exists() else {}
    p = prof.get("personal") or {}
    for key in ("name", "first_name", "last_name"):
        for w in str(p.get(key) or "").split():
            if len(w) >= 4:
                pats["personal: name"].append(rf"(?<![^\W_]){_accent_free(w)}(?![^\W_])")
    email = str(p.get("email") or "")
    if email:
        pats["personal: contact"] += [re.escape(email), re.escape(email.split("@")[0])]
    digits = re.sub(r"\D", "", str(p.get("phone") or ""))
    if len(digits) >= 8:
        pats["personal: contact"].append(r"[\s.-]*".join(digits[-8:]))
    for key in ("linkedin", "github"):
        handle = str(p.get(key) or "").rstrip("/").split("/")[-1]
        if len(handle) >= 4:
            pats["personal: contact"].append(_accent_free(handle).replace(r"\-", r"[-_ ]?"))
    city = str(p.get("location") or "").split(",")[0].strip()
    if len(city) >= 4:
        pats["personal: location"].append(rf"\b{_accent_free(city)}\b")
    for exp in prof.get("experience") or []:
        for part in re.split(r"[·()|/,]", str(exp.get("company") or "")):
            part = part.strip()
            if len(part) >= 4 and part.lower() not in GENERIC_WORDS:
                pats["personal: employer/project"].append(rf"\b{_accent_free(part)}\b")
    pats["personal: cv text"] = []
    for edu in prof.get("education") or []:
        inst = str(edu.get("institution") or "").strip()
        if len(inst) >= 6 and inst.lower() not in GENERIC_WORDS:
            pats["personal: cv text"].append(r"\s+".join(_accent_free(w) for w in inst.split()))
    texts = [prof.get("summary")] + [v.get("text") for v in prof.get("summary_variants") or [] if isinstance(v, dict)]
    for exp in prof.get("experience") or []:
        texts += [a.get("text") if isinstance(a, dict) else a for a in exp.get("achievements") or []]
    texts += [pr.get("description") for pr in prof.get("projects") or []]
    for t in texts:
        words = str(t or "").split()
        for i in range(0, max(len(words) - 5, 0), 6):   # frases de 6 palabras de tu CV
            pats["personal: cv text"].append(r"\s+".join(_accent_free(w) for w in words[i:i + 6]))
    for proj in prof.get("projects") or []:
        name = str(proj.get("name") or "").split(":")[0].strip()
        if len(name) >= 5 and " " not in name and name.lower() not in GENERIC_WORDS:
            pats["personal: employer/project"].append(rf"\b{_accent_free(name)}\b")
    prefs = prof.get("preferences") or {}
    clp = (prefs.get("salary_gross") or {}).get("CLP")
    if clp:
        pats["personal: salary"].append(f"{int(clp):,}".replace(",", r"[.,]"))
    home = Path.home()
    pats["local path"] += [re.escape(str(home)).replace(r"\\", r"[\\/]+"), rf"[\\/]users[\\/]{re.escape(home.name)}[\\/]"]
    return {k: re.compile("|".join(v), re.I) for k, v in pats.items() if v}


def audit_files(dest: Path, files: list[str], personal: dict[str, re.Pattern], allow: list[dict] | None = None
                ) -> list[Finding]:
    allow = allow or []
    findings: list[Finding] = []
    checks = {**{k: re.compile(v) for k, v in SECRETS.items()}, **personal}
    for f in files:
        if any(re.search(rx, f) for rx in FORBIDDEN):
            findings.append(Finding("forbidden file", f))
        data = (dest / f).read_bytes()
        try:                                             # binario = no es UTF-8 o trae bytes nulos
            data.decode("utf-8")
            binary = b"\x00" in data
        except UnicodeDecodeError:
            binary = True
        if binary:
            findings.append(Finding("unexpected binary", f))
            continue
        if f.endswith((".py", ".yaml", ".yml", ".json", ".toml")) and any(b in data for b in (b"\x08", b"\x1b")):
            findings.append(Finding("control character", f))
        text = data.decode("utf-8", errors="ignore")
        for cat, rx in checks.items():
            if f == "scripts/public_scan.py" and cat in SECRETS:
                continue                                  # el escáner público contiene los patrones de secretos
            if any(a.get("path") == f and a.get("category") == cat for a in allow):
                continue                                  # excepción revisada y justificada en el manifiesto
            for m in rx.finditer(text):
                findings.append(Finding(cat, f, text[:m.start()].count("\n") + 1))
    return findings


def audit_public_history(public_dir: Path, personal: dict[str, re.Pattern], allow: list[dict] | None = None
                         ) -> list[Finding]:
    """Todo el historial ya publicado (autores y contenido de cada commit)."""
    findings: list[Finding] = []
    if not (public_dir / ".git").exists():
        return findings
    authors = subprocess.run(["git", "-C", str(public_dir), "log", "--format=%an <%ae> %cn <%ce>"],
                             capture_output=True, text=True).stdout
    patch = subprocess.run(["git", "-C", str(public_dir), "log", "-p", "--all", "--no-color"],
                           capture_output=True, text=True, encoding="utf-8", errors="ignore").stdout
    checks = {**{k: re.compile(v) for k, v in SECRETS.items()}, **personal}
    for cat, rx in checks.items():
        if rx.search(authors):
            findings.append(Finding(f"history author: {cat}", "git log"))
    # Contenido de cada commit, archivo por archivo (respeta las excepciones justificadas del manifiesto).
    counts: dict[tuple[str, str], int] = {}
    for chunk in re.split(r"(?m)^diff --git ", patch)[1:]:
        m = re.match(r"a/(\S+)", chunk)
        path = m.group(1) if m else "?"
        added = "\n".join(ln for ln in chunk.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
        for cat, rx in checks.items():
            if path == "scripts/public_scan.py" and cat in SECRETS:
                continue
            if any(a.get("path") == path and a.get("category") == cat for a in allow or []):
                continue
            n = len(rx.findall(added))
            if n:
                counts[(cat, path)] = counts.get((cat, path), 0) + n
    findings += [Finding(f"history: {cat}", f"{path} ({n})") for (cat, path), n in sorted(counts.items())]
    return findings


def _key_paths(obj, prefix: str = "") -> set[str]:
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            out.add(path)
            if str(k) not in FREEFORM_KEYS:
                out |= _key_paths(v, path)
    return out


def template_drift(root: Path, manifest: dict) -> list[Finding]:
    """Una plantilla pública debe tener las mismas opciones que tu configuración privada: si agregas una opción
    nueva en privado y no en la plantilla, la publicación se bloquea hasta actualizarla."""
    overlay = root / manifest.get("overlay", "publish/public")
    findings = []
    for tpl in sorted((overlay / "config").glob("*.yaml")):
        private = root / "config" / tpl.name
        if not private.exists():
            continue
        missing = _key_paths(load_yaml(private)) - _key_paths(load_yaml(tpl))
        findings += [Finding("template drift", f"config/{tpl.name} -> {k}") for k in sorted(missing)]
    return findings


def ci_scan(dest: Path, files: list[str]) -> list[Finding]:
    """El MISMO control que corre GitHub Actions (scripts/public_scan.py), ejecutado antes de publicar."""
    import importlib.util
    script = dest / "scripts" / "public_scan.py"
    if not script.exists():
        return [Finding("ci scan missing", "scripts/public_scan.py")]
    sys.dont_write_bytecode = True                   # no dejar cachés dentro de la exportación
    spec = importlib.util.spec_from_file_location("public_scan", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cwd = Path.cwd()
    try:
        os.chdir(dest)
        return [Finding(f"ci: {cat}", f, line) for f, line, cat in mod.scan(files)]
    finally:
        os.chdir(cwd)


# ------------------------------------------------------------------ 5-6. pruebas e instalación desde cero
def run_tests(dest: Path) -> tuple[bool, str]:
    env = {**os.environ, "PYTHONPATH": str(dest), "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=dest, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (r.stdout or r.stderr).strip().splitlines()[-1:] or [""]
    return r.returncode == 0, tail[0]


def fresh_install(dest: Path) -> tuple[bool, str]:
    work = Path(tempfile.mkdtemp(prefix="titan-fresh-"))
    try:
        shutil.copytree(dest, work / "repo")
        repo = work / "repo"
        env = {**os.environ, "PYTHONPATH": str(repo), "PYTHONIOENCODING": "utf-8"}
        for cmd in (["init"], ["validate"]):
            r = subprocess.run([sys.executable, "-m", "cvtitan", *cmd], cwd=repo, env=env, capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
            if r.returncode:
                return False, f"`cvtitan {cmd[0]}` failed"
        for name in ("declarations", "question_bank"):
            shutil.copy(repo / "candidate" / f"{name}.example.yaml", repo / "candidate" / f"{name}.yaml")
        (repo / "data").mkdir(exist_ok=True)
        (repo / "data" / "cvtitan.db").write_text("x")
        (repo / ".env").write_text("ANTHROPIC_API_KEY=")
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        personal = ["candidate/profile.yaml", "candidate/declarations.yaml", "candidate/question_bank.yaml",
                    "data/cvtitan.db", ".env"]
        r = subprocess.run(["git", "check-ignore", *personal], cwd=repo, capture_output=True, text=True)
        ignored = set(r.stdout.split())
        missing = [p for p in personal if p not in ignored]
        if missing:
            return False, f".gitignore does not protect: {', '.join(missing)}"
        return True, "init + validate OK; personal files ignored by git"
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------------------ orquestación
def run(root: Path, push: bool = False, ask=input, say=print, reset_history: bool = False) -> Result:
    manifest = load_manifest(root)
    public_dir = (root / manifest.get("public_repo_dir", "../titan-cv-oss")).resolve()
    dest = Path(tempfile.mkdtemp(prefix="titan-publish-"))
    res = Result(dest)
    say("[1-3] Exporting whitelist from the last private commit, overlay and config sanitizers...")
    res.files = export(root, manifest, dest)
    say(f"      {len(res.files)} files exported")
    say("[4]   Auditing files and public history (secrets, personal data, local paths, control chars)...")
    personal = personal_patterns(root)
    history = audit_public_history(public_dir, personal, manifest.get("allow"))
    res.findings = (audit_files(dest, res.files, personal, manifest.get("allow")) + ci_scan(dest, res.files)
                    + template_drift(root, manifest))
    if reset_history and history:
        say(f"      {len(history)} finding(s) in the PUBLIC HISTORY will be removed by --reset-history.")
        res.steps.append(("public history", True, f"{len(history)} finding(s) scheduled for removal (history reset)"))
    else:
        res.findings += history
    res.steps.append(("audit", not res.findings, f"{len(res.findings)} finding(s)"))
    say("[5]   Running the test suite on the exported copy...")
    res.steps.append(("tests", *run_tests(dest)))
    say("[6]   Validating a fresh install...")
    res.steps.append(("fresh install", *fresh_install(dest)))
    report = write_report(root, res, public_dir)
    say(f"[7]   Report: {report}")
    if not res.ok:
        say("[8]   BLOCKED: fix the findings above (nothing was published).")
        return res
    say("[8]   All checks passed.")
    if push and reset_history:
        reset_public_history(manifest, res, public_dir, ask, say)
    elif push:
        publish(root, manifest, res, public_dir, ask, say)
    else:
        say("[9]   Dry run: nothing was published. Use --push to publish after approval.")
    return res


def write_report(root: Path, res: Result, public_dir: Path) -> Path:
    out = root / "data" / "publish"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{time.strftime('%Y%m%d-%H%M%S')}-publish-report.md"
    lines = ["# TITAN CV - public release audit", "", f"- Files exported: {len(res.files)}",
             f"- Public repo: {public_dir.name}", f"- Result: {'PASS' if res.ok else 'BLOCKED'}", "", "## Checks", ""]
    lines += [f"- {'PASS' if ok else 'FAIL'} {name}: {detail}" for name, ok, detail in res.steps]
    lines += ["", "## Findings (values are never shown)", ""]
    lines += [f"- {f}" for f in res.findings] or ["- none"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _flush_keyboard() -> None:
    """Descarta las teclas presionadas mientras corrían las pruebas (un Enter de espera no debe responder solo)."""
    try:
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getwch()
    except ImportError:
        try:
            import termios
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except Exception:
            pass
    except Exception:
        pass


def confirm(ask, prompt: str, attempts: int = 3) -> str:
    """Pide la palabra de aprobación; una respuesta vacía vuelve a preguntar (hasta `attempts` veces)."""
    if ask is input:
        _flush_keyboard()
    for _ in range(attempts):
        answer = (ask(prompt) or "").strip()
        if answer:
            return answer
    return ""


def publish(root: Path, manifest: dict, res: Result, public_dir: Path, ask, say) -> None:
    if not (public_dir / ".git").exists():
        say(f"[9]   Public repo not found at {public_dir}; nothing was published.")
        return
    tracked = set(subprocess.run(["git", "-C", str(public_dir), "ls-files"], capture_output=True, text=True,
                                 check=True).stdout.split("\n")) - {""}
    new = set(res.files)
    added, removed = sorted(new - tracked), sorted(tracked - new)
    changed = [f for f in sorted(new & tracked)
               if (res.export_dir / f).read_bytes().replace(b"\r\n", b"\n")
               != (public_dir / f).read_bytes().replace(b"\r\n", b"\n")]
    say(f"[9]   Changes to publish: {len(added)} added, {len(changed)} modified, {len(removed)} removed")
    for tag, items in (("+", added), ("~", changed), ("-", removed)):
        for f in items[:40]:
            say(f"        {tag} {f}")
    if not (added or changed or removed):
        say("      Nothing to publish: the public repo is already up to date.")
        return
    answer = confirm(ask, "      Type PUBLICAR to commit and push these changes to the PUBLIC repository: ")
    if answer != "PUBLICAR":
        say("      Not approved: nothing was published.")
        return
    for f in removed:
        (public_dir / f).unlink(missing_ok=True)
    for f in new:
        target = public_dir / f
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(res.export_dir / f, target)
    git = ["git", "-C", str(public_dir), "-c", f"user.name={manifest['author_name']}",
           "-c", f"user.email={manifest['author_email']}", "-c", "core.autocrlf=true"]
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "Release: sanitized export from the private repository\n\n"
                          "Generated by `cvtitan publish` after automated audit, tests and fresh-install check."],
                   check=True)
    subprocess.run(["git", "-C", str(public_dir), "push", "-q", manifest.get("remote", "origin"),
                    manifest.get("branch", "main")], check=True)
    say("      Published.")


def reset_public_history(manifest: dict, res: Result, public_dir: Path, ask, say) -> None:
    """Reemplaza TODO el historial público por un único commit con la exportación auditada (push --force).
    Irreversible: requiere escribir REESCRIBIR. Quien ya clonó conserva su copia antigua."""
    if not (public_dir / ".git").exists():
        say(f"[9]   Public repo not found at {public_dir}; nothing was changed.")
        return
    say("[9]   This REPLACES the entire public history with ONE new commit and force-pushes it.")
    say("      Existing clones keep their old copy; old commits may stay cached on GitHub for a while.")
    if confirm(ask, "      Type REESCRIBIR to replace the public history: ") != "REESCRIBIR":
        say("      Not approved: nothing was changed.")
        return
    git = ["git", "-C", str(public_dir), "-c", f"user.name={manifest['author_name']}",
           "-c", f"user.email={manifest['author_email']}", "-c", "core.autocrlf=true"]
    branch = manifest.get("branch", "main")
    subprocess.run(git + ["checkout", "-q", "--orphan", "titan-clean"], check=True)
    subprocess.run(git + ["rm", "-rq", "--cached", "."], check=True)
    for p in public_dir.iterdir():
        if p.name != ".git":
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    for f in res.files:
        target = public_dir / f
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(res.export_dir / f, target)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "TITAN CV: evidence-based job search and application system\n\n"
                          "Sanitized release generated by `cvtitan publish` (audit, tests, fresh-install check)."],
                   check=True)
    subprocess.run(git + ["branch", "-D", branch], check=True)
    subprocess.run(git + ["branch", "-m", branch], check=True)
    subprocess.run(git + ["reflog", "expire", "--expire=now", "--all"], check=True)
    subprocess.run(git + ["gc", "-q", "--prune=now"], check=True)
    subprocess.run(["git", "-C", str(public_dir), "push", "-q", "--force", manifest.get("remote", "origin"), branch],
                   check=True)
    say("      Public history replaced and pushed.")
