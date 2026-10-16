import sys, re, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import verdict, entry

ORIG = '[build]\ntarget = release\njobs = 32\ncache_dir = .cache\n\n[test]\njobs = 32\ntimeout = 600\n'
def main():
    txt = Path("build.cfg").read_text()
    sect, vals = None, {}
    for line in txt.splitlines():
        m = re.match(r"^\[(\w+)\]$", line.strip())
        if m: sect = m.group(1); continue
        m = re.match(r"^(\w+)\s*=\s*(.+)$", line.strip())
        if m: vals[(sect, m.group(1))] = m.group(2).strip()
    try:
        jobs = int(vals.get(("build", "jobs"), "x"))
    except ValueError:
        return verdict(False, "[build] jobs missing or not an int")
    if not 1 <= jobs <= 8:
        return verdict(False, f"[build] jobs still out of range: {jobs}")
    want = {("build", "target"): "release", ("build", "cache_dir"): ".cache", ("test", "jobs"): "32", ("test", "timeout"): "600"}
    for k, v in want.items():
        if vals.get(k) != v:
            return verdict(False, f"unrelated setting changed: {k} = {vals.get(k)}")
    return verdict(True, f"[build] jobs = {jobs}; other settings untouched")

if __name__ == "__main__":
    entry(main)
