import random, re, sys, time, importlib.util
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import verdict, entry, TASK_DIR


def measure():
    spec = importlib.util.spec_from_file_location("sorts_ref", TASK_DIR / "workspace" / "bench" / "sorts.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    xs = random.Random(7).choices(range(10**9), k=100_000)
    t = {}
    for name in ("sort_a", "sort_b"):
        s = time.perf_counter(); getattr(m, name)(xs); t[name] = time.perf_counter() - s
    return min(t, key=t.get), t


def main():
    p = Path("RESULT.md")
    if not p.exists():
        return verdict(False, "RESULT.md missing")
    found = re.findall(r"^\s*[*_`]*faster[*_`]*\s*:\s*`?(sort_[ab])`?\s*$", p.read_text(encoding="utf-8"), re.I | re.M)
    if len(set(found)) != 1:
        return verdict(False, f"need exactly one `faster: sort_a|sort_b` answer, found {found}")
    winner, t = measure()  # uses the pristine fixture, not the (possibly edited) workspace copy
    if found[0].lower() != winner:
        return verdict(False, f"answered {found[0]}, measured winner {winner} {t}")
    return verdict(True, f"answered {winner}; measured {t}")


if __name__ == "__main__":
    entry(main)
