cd ~/h2
sudo kill 52631 2>/dev/null; sleep 1
[ -d env-rerun-1031d ] && mv env-rerun-1031d env-rerun-1031d-argfail-late
sed -i "s/-f name=e1031c- -f name=e1031e-/-f name=e1031/; s/e1031c-sonnet e1031e-opus/e1031c-sonnet e1031f-opus/" cap270-vm1.sh
grep -n "e1031" cap270-vm1.sh
PFX=e1031f STOPAT=270 OB=$HOME/wt-main1031 setsid nohup $HOME/wt-main1031/thesis/ab/h2env/env_rerun_drive.sh $HOME/h2/spec-1031d.txt env-rerun-1031d > env-rerun-1031d.out 2>&1 < /dev/null &
sleep 3; setsid nohup $HOME/h2/cap270-vm1.sh > /dev/null 2>&1 < /dev/null &
sleep 75; sudo docker ps --format "{{.Names}} {{.Status}}"; ps -eo pid,args | grep -E "[c]ap27|[e]nv_rerun_drive"; tail -3 env-rerun-1031d/opus/run.log; ls env-rerun-1031d
