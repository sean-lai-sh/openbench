#!/bin/bash
# Pack #245 cachediv run: raw archive (off-repo, VM), raw sha256 manifest, sanitized+scrubbed copy for the data PR.
set -euo pipefail
. ~/venv/bin/activate
N=matched245-cachediv-1112; O=~/h2/$N; S=~/h2/m245c-stage; ARC=~/h2/$N-raw.tgz
cp ~/h2/m245c-div.py ~/h2/m245c-tab.py ~/h2/m245c-x.py ~/h2/m245c-pack.sh $O/ 2>/dev/null || true
[ -e $ARC ] || tar -C ~/h2 -czf $ARC $N
sha256sum $ARC | sed "s#  .*#  $N-raw.tgz#" > $O.raw-archive.sha256
rm -rf $S; mkdir -p $S/pre $S/out/results/$N
cp -a $O/. $S/pre/
( cd $O && find . -type f -print0 | sort -z | xargs -0 sha256sum | while read -r h p; do echo "$h $(stat -c %s "$p") ${p#./}"; done ) > $S/raw-sha256.txt
# drop credential headers from the cache-miss header logs (copy only; originals untouched)
python3 - "$S/pre" <<'PY'
import json, glob, sys
for f in glob.glob(sys.argv[1] + "/cells/*/pi/proxy-ledger/*.cache-miss-headers.jsonl"):
    out = []
    for l in open(f):
        if not l.strip(): continue
        r = json.loads(l)
        for sec in ("request_headers", "upstream_headers"):
            h = r.get(sec) or {}
            for k in list(h):
                if k.lower() in ("authorization", "x-api-key", "proxy-authorization", "cookie", "host"): h[k] = "<REMOVED>"
        out.append(json.dumps(r))
    open(f, "w").write("\n".join(out) + "\n")
PY
python3 ~/ob-m245b/obench/scrub.py $S/pre --out $S/out/results/$N/raw --hostname "$(hostname)" --hostname "$(hostname -f)" > $S/scrub.log 2>&1
mkdir -p $S/out/results/$N/analysis
mv $S/out/results/$N/raw/divergence.json $S/out/results/$N/raw/per-call.json $S/out/results/$N/raw/per-call.md $S/out/results/$N/analysis/
cp $S/raw-sha256.txt $S/out/results/$N/request-bodies-raw-sha256.txt
cp $O.raw-archive.sha256 $S/out/results/$N/request-bodies-raw-archive.sha256
( cd $S/out/results/$N && sha256sum raw/m245c-*.py raw/m245c-*.sh ) > $S/out/results/$N/analysis/SCRIPTS-committed.sha256
( cd $O && sha256sum m245c-*.py m245c-*.sh ) > $S/out/results/$N/analysis/SCRIPTS-as-run.sha256
echo "== check bodies+ledgers"; python3 ~/ob-m245b/obench/scrub.py --check $S/out/results/$N/raw > $S/check.log 2>&1 && echo CLEAN || { echo "HITS:"; cut -c1-200 $S/check.log | head -40; }
grep -rl -i -e "ya29\." -e "Bearer " -e "sk-ant" $S/out || echo "no credential strings"
tar -C $S/out -czf ~/h2/m245c-scrub.tgz results
sha256sum $ARC ~/h2/m245c-scrub.tgz; du -sh $S/out
