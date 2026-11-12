#!/bin/bash
set -u
S=$HOME/s243-1112
mkdir -p $S
cd ~/ob
git fetch -q origin main cursor/opencode-sonnet-model-eddf 2>&1
for pair in pr:151e349cbe6edd40855273115502f5ac2d7f54a9 base:39875fac6670b24c1cef2635aaf077e5c6e04741; do
  n=${pair%%:*}; sha=${pair#*:}
  git -C ~/ob worktree add --detach $S/wt-$n $sha >$S/$n-worktree.log 2>&1
  echo "head=$(git -C $S/wt-$n rev-parse HEAD) host=$(hostname) user=$(whoami) python=$(python3 --version 2>&1) date=$(TZ=America/New_York date '+%F %T %Z')" > $S/$n-env.txt
  python3 -m venv $S/venv-$n && $S/venv-$n/bin/pip install -e $S/wt-$n > $S/$n-install.log 2>&1; echo install_exit=$? >> $S/$n-install.log
done
run(){ n=$1; cd $S/wt-$n; env -u ANTHROPIC_API_KEY -u ANTHROPIC_BASE_URL -u OPENAI_API_KEY -u GOOGLE_APPLICATION_CREDENTIALS -u GOOGLE_CLOUD_PROJECT -u GCLOUD_PROJECT $S/venv-$n/bin/python -m unittest discover -s obench/tests -v > $S/$n-unittest.log 2>&1; echo "unittest_exit=$?" >> $S/$n-unittest.log; }
run pr & run base & wait
cd $S/wt-pr; ( echo "=== obench validate --no-imported ==="; $S/venv-pr/bin/obench validate --no-imported; echo validate_exit=$? ) > $S/pr-validate.log 2>&1
$S/venv-pr/bin/python -c "import pytest" > $S/pytest-check.txt 2>&1; echo "venv pytest exit=$?" >> $S/pytest-check.txt
python3 -c "import pytest" >> $S/pytest-check.txt 2>&1; echo "system python3 pytest exit=$?" >> $S/pytest-check.txt
touch $S/DONE
