import ast
import sys
from pathlib import Path

tree = ast.parse(Path("limits.py").read_text(encoding="utf-8"))


def retries(name: str) -> int:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    target = stmt.targets[0]
                    if isinstance(target, ast.Name) and target.id == "retries":
                        return ast.literal_eval(stmt.value)
    print(f"{name} has no retries assignment", file=sys.stderr)
    raise SystemExit(1)


remote = retries("fetch_remote")
other = retries("fetch_local")
if remote != 5 or other != 3:
    print(f"fetch_remote retries={remote}, fetch_local retries={other}", file=sys.stderr)
    raise SystemExit(1)
print("fetch_remote retries=5 and fetch_local retries=3")
