set -x
T=$HOME/ob-pr134/data/packs/openbench-tb-hard/polyglot-rust-c
cd ~/ob-pr134 && git log -1 --format=%H
git -C ~/ob-pr134 diff --quiet 65f1c985 -- data/packs/openbench-tb-hard/polyglot-rust-c 2>/dev/null; echo "pack-diff-vs-65f1c985 rc=$? (0=identical)"
sha256sum $T/solution/polyglot/main.rs $T/checker.sh $T/checker_data/harbor-tests/*
which rustc g++; rustc --version; g++ --version | head -1
echo "### A: host-side, exactly as run.py _run_checker does (cwd=workspace, TASK_DIR)"
W=$(mktemp -d $HOME/chk-host.XXXX); mkdir -p $W/polyglot; cp $T/solution/polyglot/main.rs $W/polyglot/
(cd $W && TASK_DIR=$T bash $T/checker.sh); echo "CHECKER_EXIT_A=$?"
echo "### B: inside h1-env:1027-strace"
W2=$(mktemp -d $HOME/chk-img.XXXX); mkdir -p $W2/polyglot; cp $T/solution/polyglot/main.rs $W2/polyglot/
docker run --rm -v $T:/task:ro -v $W2:/work -w /work -e TASK_DIR=/task h1-env:1027-strace bash -c 'id; which rustc g++; rustc --version; g++ --version|head -1; bash /task/checker.sh; echo CHECKER_EXIT_B=$?'
echo "### C: agent answers (from transcripts) not needed; done"
