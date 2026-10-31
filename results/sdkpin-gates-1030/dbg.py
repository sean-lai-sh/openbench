import sys; sys.path.insert(0, "/ob")
import shutil, sys, glob, os
_r = shutil.rmtree
def keep(p, *a, **k):
    if "opencode_home_" in str(p): return
    return _r(p, *a, **k)
shutil.rmtree = keep
os.environ["OBENCH_ANTHROPIC_PIN"] = sys.argv[1]
from thesis.ab import run_ab
try:
    run_ab.main(["/h2/h2prs.csv", "--pr", sys.argv[2], "--trials", "1", "--tasks-dir", "/ob/data/packs/openbench-tb-hard",
      "--tasks", "model-extraction-relu-logits", "--timeout", "20", "--timeout-cap-s", "20", "--cell-meta", "--jobs", "1",
      "--vertex-model", "claude-sonnet-5-5", "--out", "/tmp/dbgout", "--cache", "/h1/opencode-src", "--max-cost-usd", "0.05"])
except SystemExit: pass
for f in glob.glob("/tmp/opencode_home_*/.local/share/opencode/log/*.log"):
    print("=====", f); print(open(f).read()[-3000:])
