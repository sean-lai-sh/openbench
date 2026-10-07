import ast
import sys
import traceback
from pathlib import Path


def main() -> int:
    path = Path("limits.py")
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except OSError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        print("OBENCH_VERDICT: fail")
        return 1
    except SyntaxError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        print("OBENCH_VERDICT: fail")
        return 1

    def retries(name: str) -> int:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                        target = stmt.targets[0]
                        if isinstance(target, ast.Name) and target.id == "retries":
                            return ast.literal_eval(stmt.value)
        print(f"{name} has no retries assignment", file=sys.stderr)
        return -1

    remote = retries("fetch_remote")
    other = retries("fetch_local")
    if remote != 5 or other != 3:
        print(f"fetch_remote retries={remote}, fetch_local retries={other}", file=sys.stderr)
        print("OBENCH_VERDICT: fail")
        return 1
    print("fetch_remote retries=5 and fetch_local retries=3")
    print("OBENCH_VERDICT: pass")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
