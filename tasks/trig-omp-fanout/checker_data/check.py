import ast, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import verdict, run_hidden_tests, entry


def main():
    left = []
    for p in Path(".").rglob("*.py"):
        if any(part.startswith(".") for part in p.parts):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as e:
            return verdict(False, f"{p}: syntax error {e}")
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr == "utcnow":
                left.append(f"{p}:{n.lineno}")
    if left:
        return verdict(False, "utcnow still used: " + ", ".join(left))
    rc, out = run_hidden_tests()
    if rc != 0:
        return verdict(False, "hidden suite failed:\n" + out)
    return verdict(True, "no utcnow left; all datetimes tz-aware; tests pass")


if __name__ == "__main__":
    entry(main)
