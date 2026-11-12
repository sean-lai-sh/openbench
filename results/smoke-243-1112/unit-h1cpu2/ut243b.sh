#!/bin/bash
set -u
umask 022
S=$HOME/s243-1112
F=$S/full
L=$S/run2
mkdir -p $L
cd $S
git clone -q --filter=blob:none --no-checkout https://github.com/sean-lai-sh/openbench.git $F > $L/clone.log 2>&1
cd $F && git fetch -q origin 151e349cbe6edd40855273115502f5ac2d7f54a9 >> $L/clone.log 2>&1
git checkout -q --detach 39875fac6670b24c1cef2635aaf077e5c6e04741 >> $L/clone.log 2>&1; echo checkout_exit=$? >> $L/clone.log
echo "sparse=$(git config --get core.sparseCheckout)" >> $L/clone.log; du -sh $F >> $L/clone.log; df -h / | tail -1 >> $L/clone.log
python3 -m venv $S/venv-full && $S/venv-full/bin/pip install -e $F > $L/install.log 2>&1; echo install_exit=$? >> $L/install.log
run(){ n=$1; sha=$2; cd $F; git checkout -q --detach $sha; git status --short | head > $L/$n-status.txt
  echo "head=$(git rev-parse HEAD) host=$(hostname) user=$(whoami) umask=$(umask) python=$(python3 --version 2>&1) start=$(TZ=America/New_York date '+%F %T %Z')" > $L/$n-env.txt
  env -u ANTHROPIC_API_KEY -u ANTHROPIC_BASE_URL -u OPENAI_API_KEY -u GOOGLE_APPLICATION_CREDENTIALS -u GOOGLE_CLOUD_PROJECT -u GCLOUD_PROJECT $S/venv-full/bin/python -m unittest discover -s obench/tests -v > $L/$n-unittest.log 2>&1; echo "unittest_exit=$?" >> $L/$n-unittest.log; }
run base 39875fac6670b24c1cef2635aaf077e5c6e04741
run pr 151e349cbe6edd40855273115502f5ac2d7f54a9
cd $F; ( echo "=== obench validate --no-imported (head $(git rev-parse HEAD)) ==="; $S/venv-full/bin/obench validate --no-imported; echo validate_exit=$? ) > $L/pr-validate.log 2>&1
touch $L/DONE
