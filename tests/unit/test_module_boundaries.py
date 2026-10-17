"""Module boundary rule: other modules import only a module's public API (its ``__init__``).

Exceptions: ``aqta.core.*`` (shared kernel, see its docstring), and ``aqta.<module>.adapters``
imported from the composition roots (``aqta.api`` / ``aqta.worker``) for wiring.
Import-linter (pyproject.toml) enforces the dependency-direction contracts on top of this.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "aqta"
COMPOSITION_ROOTS = {"api", "worker"}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
    return names


def test_cross_module_imports_use_public_api() -> None:
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC)
        if len(rel.parts) < 2:
            continue
        owner = rel.parts[0]
        for name in _imports(path):
            parts = name.split(".")
            if parts[0] != "aqta" or len(parts) < 3:
                continue
            target, sub = parts[1], parts[2]
            if target in (owner, "core"):
                continue
            if sub == "adapters" and owner in COMPOSITION_ROOTS:
                continue
            violations.append(f"{rel}: imports {name}")
    assert violations == [], "\n".join(violations)
