#!/bin/bash
# Pack #245 gate smoke: raw archive (off-repo, VM) + sha256 manifest; sanitized + scrubbed copy for the data PR.
set -euo pipefail
. ~/venv/bin/activate
N=matched245-gate-1112; O=~/h2/$N; S=~/h2/m245g-stage; ARC=~/h2/$N-raw.tgz
cp ~/h2/m245g-an.py ~/h2/m245g-pack.sh ~/h2/m245g-proof.py ~/h2/m245g-readme.py $O/
tar -C ~/h2 -czf $ARC $N
sha256sum $ARC | sed "s#  .*#  $N-raw.tgz#" > $O.raw-archive.sha256
rm -rf $S; mkdir -p $S/pre $S/out/results/$N
cp -a $O/. $S/pre/
( cd $O && find . -type f -print0 | sort -z | xargs -0 sha256sum | while read -r h p; do echo "$h $(stat -c %s "$p") ${p#./}"; done ) > $S/raw-sha256.txt
# received.bin are JSON bytes: rename in the copy so scrub.py treats them as text
find $S/pre -name '*.received.bin' -exec sh -c 'mv "$1" "${1%.bin}.json"' _ {} \;
python3 - "$S/pre" <<'PY'
import json, glob, sys
for f in glob.glob(sys.argv[1] + "/cells/*/*/proxy-ledger/*.cache-miss-headers.jsonl"):
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
python3 ~/ob-m245g/obench/scrub.py $S/pre --out $S/out/results/$N/raw --hostname "$(hostname)" --hostname "$(hostname -f)" > $S/scrub.log 2>&1
mkdir -p $S/out/results/$N/analysis
mv $S/out/results/$N/raw/analysis.json $S/out/results/$N/raw/opencode-proof.json $S/out/results/$N/analysis/
echo 776441123884afd1d2efdc3445c295afc5d372bb > $S/out/results/$N/raw/head.txt
cp $S/raw-sha256.txt $S/out/results/$N/request-bodies-raw-sha256.txt
cp $O.raw-archive.sha256 $S/out/results/$N/request-bodies-raw-archive.sha256
( cd $O && sha256sum m245g-*.py m245g-*.sh ) > $S/out/results/$N/analysis/SCRIPTS-as-run.sha256
( cd $S/out/results/$N/raw && sha256sum m245g-*.py m245g-*.sh ) > $S/out/results/$N/analysis/SCRIPTS-committed.sha256
echo "== check"; python3 ~/ob-m245g/obench/scrub.py --check $S/out/results/$N/raw > $S/check.log 2>&1 && echo CLEAN || { echo "HITS:"; grep -v '^ *line' $S/check.log | head -30; grep '^ *line' $S/check.log | awk '{print $3}' | sort | uniq -c; }
grep -rlI -e "ya29\." -e "Bearer [A-Za-z0-9]" $S/out || echo "no credential strings"
find $S/out -type f ! -name '*.json' ! -name '*.jsonl' ! -name '*.txt' ! -name '*.log' ! -name '*.md' ! -name '*.py' ! -name '*.sh' ! -name '*.out' ! -name '*.sha256' | head
tar -C $S/out -czf ~/h2/m245g-scrub.tgz results
sha256sum $ARC ~/h2/m245g-scrub.tgz; du -sh $S/out
