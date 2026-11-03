"""Live spend for the gate driver: proxy-ledger token cost (list price) per pair and total."""
import glob, json, sys
sys.path.insert(0, sys.argv[3])
from thesis.ab.summarize import proxy_cost_from_records
def cost(root):
    recs = []
    for f in glob.glob(f"{root}/**/proxy-ledger/*.jsonl", recursive=True):
        for line in open(f):
            try: recs.append(json.loads(line))
            except ValueError: pass
    c = proxy_cost_from_records(recs, default_model="claude-opus-5-5")
    return -1.0 if c is None else c
print(f"{cost(sys.argv[1]):.4f} {cost(sys.argv[2]):.4f}")
