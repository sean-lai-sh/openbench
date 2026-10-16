import sys, re, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import verdict, entry

GOLDEN = Path("services/cart/tests/integration/snapshots/golden")
def main():
    f = GOLDEN / "empty_cart.json"
    if not f.is_file():
        return verdict(False, f"{f} missing")
    try:
        data = json.loads(f.read_text())
    except Exception as e:
        return verdict(False, f"invalid json: {e}")
    if data != {"items": [], "total": 0}:
        return verdict(False, f"wrong contents: {data!r}")
    strays = [str(p) for p in Path(".").rglob("empty_cart.json") if p.parent != GOLDEN]
    if strays:
        return verdict(False, "fixture also written outside the golden dir: " + ", ".join(strays))
    lines = (GOLDEN / "MANIFEST.txt").read_text().splitlines()
    if not any(re.match(r"^empty_cart\.json\s*\|\s*\S", l) for l in lines):
        return verdict(False, "empty_cart.json not registered in MANIFEST.txt as `name | description`")
    for keep in ("one_item.json |", "two_items.json |"):
        if not any(l.startswith(keep) for l in lines):
            return verdict(False, f"existing manifest entry lost: {keep}")
    return verdict(True, "fixture added to golden dir and registered")

if __name__ == "__main__":
    entry(main)
