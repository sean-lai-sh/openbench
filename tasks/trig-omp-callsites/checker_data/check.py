import ast, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import verdict, run_hidden_tests, entry


def main():
    left = []
    for p in sorted(Path(".").rglob("*.py")):
        if any(x.startswith(".") for x in p.parts):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as e:
            return verdict(False, f"{p}: syntax error {e}")
        for n in ast.walk(tree):
            hit = (isinstance(n, ast.Name) and n.id == "legacy_fetch") or \
                  (isinstance(n, ast.Attribute) and n.attr == "legacy_fetch") or \
                  (isinstance(n, ast.FunctionDef) and n.name == "legacy_fetch") or \
                  (isinstance(n, ast.alias) and n.name == "legacy_fetch")
            if hit:
                left.append(f"{p}:{getattr(n, 'lineno', '?')}")
    if left:
        return verdict(False, f"{len(left)} code references to legacy_fetch remain: " + ", ".join(left[:10]))
    rc, out = run_hidden_tests()
    if rc != 0:
        return verdict(False, "hidden suite failed:\n" + out)
    return verdict(True, "all 35 call sites use fetch_v2; legacy_fetch removed")


if __name__ == "__main__":
    entry(main)
