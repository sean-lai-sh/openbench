import sys, re, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import verdict, entry

ORIG = '# API limits\n\nLimits are per API key. Bursts above the limit get HTTP 429.\n\n| Endpoint | Limit | Burst | Notes |\n|---|---|---|---|\n| `GET /items` | 600/min | 50 | cached at edge |\n| `POST /items` | 60/min | 10 | idempotency key required |\n| `GET /search` | 60/min | 20 | `q` max 256 chars \\| no wildcards |\n| `POST /export` | 5/hour | 1 | async; poll `/jobs` |\n\nContact support to raise a limit.\n'
WANT = '# API limits\n\nLimits are per API key. Bursts above the limit get HTTP 429.\n\n| Endpoint | Limit | Burst | Notes |\n|---|---|---|---|\n| `GET /items` | 600/min | 50 | cached at edge |\n| `POST /items` | 60/min | 10 | idempotency key required |\n| `GET /search` | 120/min | 20 | `q` max 256 chars \\| no wildcards |\n| `POST /export` | 5/hour | 1 | async; poll `/jobs` |\n\nContact support to raise a limit.\n'
def main():
    got = Path("docs/limits.md").read_text()
    if got == WANT or got == WANT.rstrip("\n"):
        return verdict(True, "search row updated; table intact")
    g, w = got.splitlines(), WANT.splitlines()
    if len(g) != len(w):
        return verdict(False, f"line count changed {len(w)} -> {len(g)}")
    bad = [i + 1 for i, (a, b) in enumerate(zip(g, w)) if a != b]
    search = [i for i, l in enumerate(w) if "GET /search" in l][0]
    if bad == [search + 1]:
        cells = [c.strip() for c in g[search].strip().strip("|").split(" | ")]
        if g[search].count("|") == w[search].count("|") and cells[1] == "120/min" and cells[2] == "20" and cells[0] == "`GET /search`" and g[search].rstrip().endswith("no wildcards |"):
            return verdict(True, "search row updated (whitespace variant); table intact")
        return verdict(False, "search row malformed: " + g[search])
    return verdict(False, f"unexpected changes on lines {bad}")

if __name__ == "__main__":
    entry(main)
