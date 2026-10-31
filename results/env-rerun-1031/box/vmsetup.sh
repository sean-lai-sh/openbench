set -e
cd ~/wt-env1031b; git fetch -q origin main; [ -d ~/wt-main1031 ] || git worktree add -q --detach ~/wt-main1031 bfa88e4c0ab6d300d79e37ff26389e37167c8db8
git -C ~/wt-main1031 sparse-checkout add results/pin-table-1030/rev2; git -C ~/wt-main1031 rev-parse HEAD; ls ~/wt-main1031/results/pin-table-1030/rev2/pin-table.csv
