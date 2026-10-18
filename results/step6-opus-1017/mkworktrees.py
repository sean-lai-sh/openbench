# Recreate a PR's two OpenCode worktrees with the runner's own function (build_opencode._ensure_worktree), as done for 23771.
# usage: mkworktrees.py <PR>   (prints each path and its size)
import csv,sys,subprocess
sys.path.insert(0,'/tmp/ob-s6run')
from pathlib import Path
from thesis.ab.build_opencode import _ensure_mirror,_ensure_worktree
from thesis.ab.durable import exclusive_lock
C=Path('/workspace/openbench-ab/results/opencode-src').resolve()
row=[r for r in csv.DictReader(open('/tmp/ob-s6run/thesis/ab/fixtures/opencode-harness-prs.csv')) if r['PR']==sys.argv[1]][0]
for side,sha in (('without',row['Parent/base SHA']),('with',row['Merge commit SHA'])):
    sha=sha.strip().lower(); dest=C/'worktrees'/sha
    with exclusive_lock(C/'mirror.lock'):
        _ensure_worktree(_ensure_mirror(C),sha,dest)
    print(sys.argv[1],side,dest,subprocess.run(['du','-sh',str(dest)],capture_output=True,text=True).stdout.split()[0])
