#!/usr/bin/env python3
"""Build the committable pack for d1fu-30-1112 from the untouched run dir. Never writes into the run dir.
- raw/: run dir minus request-bodies; text files get <HOME> -> <HOME>, VM hostname -> <HOST> (digests kept);
  transcript text files are obench/scrub.py scrub_text output; binary transcript files (sqlite db/wal/shm) copied as is;
  workspace tarballs repacked with numeric owner 0/0.
- request-bodies-scrubbed/: scrub_text of every captured body (renamed .json), meta.jsonl copied as is.
- request-bodies-raw-sha256.txt: sha256 of every RAW captured file (relative to request-bodies/)."""
import hashlib, io, os, shutil, sys, tarfile
sys.path.insert(0, "<HOME>/ob-s248")
from obench import scrub
R, P = sys.argv[1], sys.argv[2]
assert not os.path.exists(P), P
HOME = "<HOME>"
HOSTS = ["<HOST>", "<HOST>"]
ctx = scrub.build_context(user="<USER>", home=HOME, hostnames=HOSTS)
def is_text(b):
    try: b.decode("utf-8"); return b"\x00" not in b
    except UnicodeDecodeError: return False
def light(t):
    t = t.replace(HOME, "<HOME>")
    for h in HOSTS: t = t.replace(h, "<HOST>")
    return t
def repack(src, dst):
    with tarfile.open(src, "r:gz") as ti, tarfile.open(dst, "w:gz") as to:
        for m in ti.getmembers():
            f = ti.extractfile(m) if m.isfile() else None
            m.uid = m.gid = 0; m.uname = m.gname = ""
            to.addfile(m, f)
counts = {"light": 0, "scrubbed": 0, "binary": 0, "tar": 0}
for root, dirs, files in os.walk(R):
    rel = os.path.relpath(root, R)
    if rel.split(os.sep)[0] in ("request-bodies", ".running"): continue
    for n in files:
        s = os.path.join(root, n); d = os.path.join(P, "raw", rel, n); os.makedirs(os.path.dirname(d), exist_ok=True)
        if n.endswith(".tar.gz"): repack(s, d); counts["tar"] += 1; continue
        b = open(s, "rb").read()
        if not is_text(b): shutil.copyfile(s, d); counts["binary"] += 1; continue
        t = b.decode("utf-8")
        if "transcripts" in rel.split(os.sep): open(d, "w").write(scrub.scrub_text(t, ctx)); counts["scrubbed"] += 1
        else: open(d, "w").write(light(t)); counts["light"] += 1
RB = os.path.join(R, "request-bodies"); man = []
for root, dirs, files in os.walk(RB):
    for n in sorted(files):
        s = os.path.join(root, n); rel = os.path.relpath(s, RB); b = open(s, "rb").read()
        man.append(f"{hashlib.sha256(b).hexdigest()}  {len(b)}  {rel}")
        d = os.path.join(P, "request-bodies-scrubbed", rel.replace(".bin", ".json")); os.makedirs(os.path.dirname(d), exist_ok=True)
        if n == "meta.jsonl" or n == "CAPTURE.txt": open(d, "w").write(light(b.decode()))
        else: open(d, "w").write(scrub.scrub_text(b.decode("utf-8"), ctx))
open(os.path.join(P, "request-bodies-raw-sha256.txt"), "w").write("# sha256  bytes  path (relative to raw request-bodies/, off-repo on <HOST>)\n" + "\n".join(sorted(man, key=lambda x: x.split("  ")[2])) + "\n")
print(counts, "bodies", len(man))
