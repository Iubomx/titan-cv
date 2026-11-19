"""cvtitan publish: la auditoría bloquea secretos y datos personales sin mostrarlos; la configuración se sanea."""
import re
from pathlib import Path

from cvtitan import publish


def _tree(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return sorted(files)


def test_audit_detects_secrets_personal_data_and_forbidden_files_without_values(tmp_path):
    fake_key = "sk-ant-" + "A1b2C3d4" * 4
    files = _tree(tmp_path, {
        "cvtitan/a.py": f'KEY = "{fake_key}"\n',
        "tests/t.py": "who = 'Ana Pérez from Valparaíso'\n",
        "candidate/profile.yaml": "name: x\n",
        "config/companies.yaml": "- name: Acme Mining\n",
        "candidate/profile.example.yaml": "ok\n",
    })
    personal = {"personal: name": re.compile(r"p[eé]rez", re.I), "personal: location": re.compile(r"valpara[ií]so", re.I),
                "personal: employer/project": re.compile(r"acme", re.I)}
    allow = [{"path": "config/companies.yaml", "category": "personal: employer/project"}]
    found = publish.audit_files(tmp_path, files, personal, allow)
    cats = {(f.category, f.path) for f in found}
    assert ("anthropic key", "cvtitan/a.py") in cats
    assert ("personal: name", "tests/t.py") in cats and ("personal: location", "tests/t.py") in cats
    assert ("forbidden file", "candidate/profile.yaml") in cats
    assert not any(p == "config/companies.yaml" for _, p in cats)          # excepción justificada
    assert not any(p == "candidate/profile.example.yaml" for _, p in cats)
    assert all(fake_key not in str(f) and "Pérez" not in str(f) for f in found)   # nunca el valor


def test_config_sanitizers_disable_sending_and_neutralize_preferences(tmp_path):
    _tree(tmp_path, {
        "config/lines.yaml": "lines:\n  A:\n    send_enabled: true  # autorizado\n  B:\n    send_enabled: true\n"
                             "    salary:\n      min_monthly: 3000\n      target_monthly: 5000\n",
        "config/auto.yaml": "# Criterio personal del candidato\n# Pretensión fija\n\nmin_score: 55\n",
        "config/job_dictionary.json": '{"roles": {}, "profile_signals": {"x": ["y"]}}',
    })
    publish.sanitize_config(tmp_path)
    lines = (tmp_path / "config/lines.yaml").read_text(encoding="utf-8")
    assert "send_enabled: true" not in lines and lines.count("send_enabled: false") == 2
    assert "min_monthly: 0" in lines and "3000" not in lines and "5000" not in lines
    auto = (tmp_path / "config/auto.yaml").read_text(encoding="utf-8")
    assert "Criterio personal" not in auto and "min_score: 55" in auto
    assert "profile_signals" not in (tmp_path / "config/job_dictionary.json").read_text(encoding="utf-8")


def test_whitelist_matching():
    inc = ["cvtitan/**", "candidate/profile.example.yaml", "docs/agent-policy.md"]
    assert publish._matches("cvtitan/ui/theme.py", inc) and publish._matches("candidate/profile.example.yaml", inc)
    assert not publish._matches("candidate/profile.yaml", inc) and not publish._matches("docs/auditoria/x.md", inc)
    assert not publish._matches("data/cvtitan.db", inc)


def test_dictionary_gets_template_priorities(tmp_path):
    roles = {r: {} for r in ["data_bi", "backend", "mining_dispatch", "frontend", "custom_role"]}
    import json
    _tree(tmp_path, {"config/job_dictionary.json": json.dumps({"roles": roles, "priority": {"P1": ["mining_dispatch"]}})})
    publish.sanitize_config(tmp_path)
    pr = json.loads((tmp_path / "config/job_dictionary.json").read_text(encoding="utf-8"))["priority"]
    assert pr["P1"] == ["data_bi", "backend"] and pr["P2"] == ["frontend"]
    assert set(pr["P3"]) == {"mining_dispatch", "custom_role"}


def test_template_drift_blocks_missing_options(tmp_path):
    _tree(tmp_path, {
        "config/auto.yaml": "min_score: 55\nnew_option: 1\ninclude:\n  mine: x\n",
        "publish/public/config/auto.yaml": "# PLANTILLA\nmin_score: 55\ninclude:\n  other: y\n",
    })
    found = publish.template_drift(tmp_path, {"overlay": "publish/public"})
    assert [str(f.path) for f in found] == ["config/auto.yaml -> new_option"]     # `include` es contenido libre


def test_confirm_reasks_on_empty_answer():
    answers = iter(["", "  ", "REESCRIBIR"])
    assert publish.confirm(lambda _p: next(answers), "?") == "REESCRIBIR"
    assert publish.confirm(lambda _p: "", "?") == ""
