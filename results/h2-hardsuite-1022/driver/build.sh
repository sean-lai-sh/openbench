#!/bin/bash
set -e
cd ~/h2build && rm -rf tests && mkdir tests
for t in ~/ob/data/packs/openbench-tb-hard/*/; do cp $t/checker_data/harbor-tests/test.sh tests/$(basename $t).sh; done
grep -c '^uvx' tests/*.sh
time sudo docker build -f Dockerfile.h2 -t h2-env:1022 . > build.log 2>&1 || { tail -30 build.log; exit 1; }
tail -5 build.log; sudo docker images h2-env
