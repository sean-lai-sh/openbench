import sys, re, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import verdict, entry

EXPECTED = ['api/v1/billing.proto', 'api/v1/users.proto', 'api/v2/users.proto', 'internal/events/order_events.proto', 'internal/rpc/health/health.proto', 'third_party/google/type/money.proto']
def main():
    p = Path("PROTOS.txt")
    if not p.is_file():
        return verdict(False, "PROTOS.txt missing")
    got = [l.strip().removeprefix("./") for l in p.read_text().splitlines() if l.strip()]
    if got != EXPECTED:
        return verdict(False, f"expected {EXPECTED}, got {got}")
    actual = sorted(str(q) for q in Path(".").rglob("*.proto"))
    if actual != EXPECTED:
        return verdict(False, f"proto files changed on disk: {actual}")
    return verdict(True, "all 6 .proto files listed, sorted")

if __name__ == "__main__":
    entry(main)
