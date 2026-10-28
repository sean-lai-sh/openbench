#!/bin/bash
set -u
O=$HOME/s8ready/r3; mkdir -p $O; E=$O/egress.txt
. $HOME/ob-fix/thesis/ab/launchers/egress_block.sh
IMG=h1-env:1027-strace
{ echo "== $(date '+%F %T %Z') before apply"; egress_verify $IMG; echo "verify rc=$? (1 = reachable, expected before apply)"
  echo "== apply"; egress_apply; egress_status
  echo "== $(date '+%F %T %Z') verify after apply"; egress_verify $IMG; echo "verify rc=$? (0 = blocked)"; } > $E 2>&1
cd $HOME/s8ready
CTL="--bin-root /cf/bin --cache /cf --capture /o/r3-c0dc/requests --control ctl-0dc80df6=/cf/bin/0dc80df6fd1f4c89cebf9ed20cd9d9291f996236/opencode=/h1/opencode-src/bin/0dc80df6fd1f4c89cebf9ed20cd9d9291f996236/opencode=0dc80df6fd1f4c89cebf9ed20cd9d9291f996236"
for i in 1 2 3; do
  EXTRA="$EGRESS_ADD_HOST" bash ./rdy.sh $HOME/ob-fix r3-3251-$i --sides /o/3251.json --bin-root /c/bin --cache /c --capture /o/r3-3251-$i/requests
done
bash ./rdy.sh $HOME/ob-fix r3-c0dc $CTL
{ echo "== $(date '+%F %T %Z') status before remove"; egress_status; echo "== remove"; egress_remove; egress_status; echo "rules left: $(egress_status | wc -l)"
  echo "== after remove"; egress_verify; echo "verify rc=$? (1 = reachable again)"; } >> $E 2>&1
touch $O/DONE
