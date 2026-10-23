#!/bin/bash
cd ~/h2build
for t in torch-pipeline-parallelism torch-tensor-parallelism sam-cell-seg; do
 cmd=$(sed -n '/^uvx/,/[^\\]$/p' tests/$t.sh | tr -d '\\\n' | sed -E 's/ pytest --ctrf.*$/ pytest --version/')
 v=$(grep -E '^[A-Z_]+=' tests/$t.sh || true)
 for img in "h1-env:1022 cold" "h2-env:1022 warm"; do set -- $img
  s=$(date +%s.%N); sudo docker run --rm $( [ $2 = cold ] && echo "-e UV_CACHE_DIR=/tmp/empty" ) $1 bash -c "cd /tmp; $v; $cmd" >/dev/null 2>&1; rc=$?; e=$(date +%s.%N)
  echo "$t $2 ($1) rc=$rc $(echo "$e - $s" | bc) s"
 done
done
s=$(date +%s.%N); sudo docker run --rm --network none h2-env:1022 bash -c "cd /tmp; uvx --offline -p 3.13 -w pytest==8.4.1 -w torch==2.7.0 -w pytest-json-ctrf==0.3.5 pytest --version"; echo "warm offline torch-tensor rc=$? $(echo "$(date +%s.%N) - $s"|bc) s"
