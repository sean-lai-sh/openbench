#!/bin/bash
set -u; cd ~/ob-fix; export PATH=$HOME/h1/opencode-src/go/1.24.6/bin:$HOME/h1/opencode-src/bun/bin:$PATH; export OPENCODE_CHANNEL=local
L=~/s8-3481local; for s in 51e4c9fc4cb4ef01f7d337127b463729c2967594 c1ada302f983f150ec42c473d316b3488318163b; do timeout 3600 python3 -m thesis.ab.build_opencode $s --cache $L > $L/$s.log 2>&1 & done; wait
: > $L/builds.jsonl; for s in 51e4c9fc4cb4ef01f7d337127b463729c2967594 c1ada302f983f150ec42c473d316b3488318163b; do python3 ~/s8f032run/rec.py $L $s ~/s8f032 >> $L/builds.jsonl; done; echo DONE > $L/status
