"""Los módulos de cvtitan/commands/ no pueden tener imports relativos rotos (el linter no ve los diferidos)."""
import ast
import importlib
import importlib.util
from pathlib import Path

import pytest

from cvtitan.cli import build_parser, main

COMMANDS_DIR = Path(__file__).resolve().parents[1] / "cvtitan" / "commands"
FILES = sorted(COMMANDS_DIR.glob("*.py"))


def _targets(path: Path):
    """(línea, módulo absoluto, nombres) de cada import relativo del archivo, incluidos los de dentro de funciones."""
    package = ["cvtitan", "commands"]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level:
            base = package[: len(package) - (node.level - 1)]
            module = ".".join(base + ([node.module] if node.module else []))
            yield node.lineno, module, [a.name for a in node.names]


def _defined_names(source_file: str) -> set[str]:
    """Nombres de primer nivel que define un módulo (sin importarlo)."""
    names: set[str] = set()
    for node in ast.parse(Path(source_file).read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                elements = target.elts if isinstance(target, ast.Tuple) else [target]   # a, b = ...
                names |= {e.id for e in elements if isinstance(e, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names |= {(a.asname or a.name).split(".")[0] for a in node.names}
    return names


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_every_relative_import_resolves(path):
    for lineno, module, names in _targets(path):
        spec = importlib.util.find_spec(module)
        assert spec is not None, f"{path.name}:{lineno}: no existe el módulo {module}"
        is_package = spec.submodule_search_locations is not None
        defined = _defined_names(spec.origin) if spec.origin else set()
        for name in names:
            if is_package and importlib.util.find_spec(f"{module}.{name}") is not None:
                continue                                         # es un submódulo
            assert name in defined, f"{path.name}:{lineno}: {module} no define {name}"


def test_parser_registers_every_command_and_each_has_help(capsys):
    parser = build_parser()
    sub = next(a for a in parser._actions if a.dest == "cmd")
    names = sorted(sub.choices)
    assert {"auto", "postular", "buscar", "demo", "web", "sesiones", "showcase", "vault", "track", "purge"} <= set(names)
    for name in names:
        with pytest.raises(SystemExit) as exc:
            main([name, "--help"])
        assert exc.value.code == 0, name
    capsys.readouterr()
