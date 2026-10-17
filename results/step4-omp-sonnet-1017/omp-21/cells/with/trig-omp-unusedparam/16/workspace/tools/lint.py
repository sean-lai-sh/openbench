"""Minimal unused-argument linter (subset of ruff ARG001)."""
import ast
import sys
from pathlib import Path


def check(path):
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if "noqa" in lines[node.lineno - 1]:
            continue
        used = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        for a in args:
            if a.arg in ("self", "cls") or a.arg.startswith("_"):
                continue
            if a.arg not in used:
                problems.append(f"{path}:{node.lineno}: ARG001 unused argument `{a.arg}` in `{node.name}`")
    return problems


def main(root="."):
    problems = []
    for p in sorted(Path(root).rglob("*.py")):
        if "tools" in p.parts or "tests" in p.parts or any(x.startswith(".") for x in p.parts):
            continue
        problems += check(p)
    for line in problems:
        print(line)
    print(f"Found {len(problems)} error(s)." if problems else "All checks passed!")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
