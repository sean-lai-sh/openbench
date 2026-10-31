set -e
cd ~/wt-env1031b; git fetch -q origin main; [ -d ~/wt-main1031 ] || git worktree add -q --detach ~/wt-main1031 bfa88e4c0ab6d300d79e37ff26389e37167c8db8
git -C ~/wt-main1031 sparse-checkout add results/pin-table-1030/rev2; git -C ~/wt-main1031 rev-parse HEAD; ls ~/wt-main1031/results/pin-table-1030/rev2/pin-table.csv
cd ~/h2; cat > spec-1031c.txt <<'SP'
opus 13331 2.0.58 /h2/h2-deferred-1023/opus 13331/without/model-extraction-relu-logits/10,13331/without/model-extraction-relu-logits/8,13331/with/torch-tensor-parallelism/7
sonnet 13331 2.0.58 /h2/h2-deferred-1023/sonnet 13331/without/model-extraction-relu-logits/4
SP
PFX=e1031g STOPAT=4.90 OB=$HOME/wt-main1031 setsid nohup $HOME/wt-main1031/thesis/ab/h2env/env_rerun_drive.sh $HOME/h2/spec-1031c.txt cells-rerun-1031c > cells-rerun-1031c.out 2>&1 < /dev/null &
sleep 20; cut -c1-200 cells-rerun-1031c/driver.log; cat cells-rerun-1031c.out; sudo docker ps --format '{{.Names}} {{.Status}}'
