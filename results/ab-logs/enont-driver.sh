#!/bin/bash
# ENOENT-set rerun @ 019ad6e / PR #8 packaging (after smoke #4838 PASS)
set -u
cd /workspace/openbench-ab
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d
export VERTEX_LOCATION=global
export GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json

CAP=700
HEADROOM=40
PRS="4204 5066 5131 5140 5527 6524"
S=results/ab-logs/setaside_stats.py
LOG=results/ab-logs/enont-driver.log
FIXTURE=thesis/ab/fixtures/opencode-harness-prs.csv
CACHE=/workspace/openbench-ab/results/opencode-src
PROGRESS=results/ab-logs/enont-progress.md
LATEST=results/ab-logs/enont-latest.txt
POSTDIR=results/ab-logs/enont-posts
REPORT=results/ab-logs/enont-report.md

mkdir -p results/ab-logs results/ab "$POSTDIR"
{
  echo "# ENOENT-set progress @ 019ad6e / PR #8"
  echo
  echo "Smoke #4838 PASS first. Soft pause CAP=\$$CAP (HEADROOM=\$$HEADROOM). Current spend at start below."
  echo
} > "$PROGRESS"
echo "starting" > "$LATEST"
echo "ENONT START $(date -Is) spend=\$$(python3 $S total) HEAD=$(git rev-parse --short HEAD)" | tee "$LOG"

post_pr() {
  local pr=$1 status=$2
  python3 - <<PY
import json, glob, statistics as st, os
from pathlib import Path
from thesis.ab.summarize import row_cost

pr = "$pr"
status = "$status"
cells = {"without": [], "with": []}
for p in glob.glob(f"results/ab/{pr}/cells/*/*/*.json"):
    d = json.load(open(p))
    side = p.split("/")[p.split("/").index("cells") + 1]
    cells[side].append(d)

def agg(rows):
    if not rows:
        return None
    n = len(rows)
    passr = sum(1 for x in rows if x.get("success")) / n
    walls = [x["wall_time_s"] for x in rows if x.get("wall_time_s") is not None]
    toks = []
    outs = []
    nonc = []
    pin = []
    pout = []
    for x in rows:
        if x.get("tokens_output") is None:
            continue
        toks.append((x.get("tokens_input_uncached") or 0) + (x.get("tokens_output") or 0) + (x.get("tokens_cache_read") or 0) + (x.get("tokens_cache_write") or 0))
        outs.append(x.get("tokens_output") or 0)
        nonc.append(x.get("tokens_input_uncached") or 0)
        if x.get("tokens_proxy_input_uncached") is not None:
            pin.append(x["tokens_proxy_input_uncached"])
        if x.get("tokens_proxy_output") is not None:
            pout.append(x["tokens_proxy_output"])
    costs = [c for c in (row_cost(x) for x in rows) if c is not None]
    pbase = {}
    for x in rows:
        k = x.get("token_basis_proxy") or x.get("token_basis")
        pbase[k] = pbase.get(k, 0) + 1
    fc = {}
    for x in rows:
        fc[x.get("failure_class")] = fc.get(x.get("failure_class"), 0) + 1
    return {
        "n": n, "pass": passr,
        "wall": st.mean(walls) if walls else None,
        "tok": st.mean(toks) if toks else None,
        "cost": st.mean(costs) if costs else None,
        "out": st.mean(outs) if outs else None,
        "nonc": st.mean(nonc) if nonc else None,
        "pin": st.mean(pin) if pin else None,
        "pout": st.mean(pout) if pout else None,
        "pbase": pbase, "fc": fc,
        "unmetered": n - len(costs),
    }

def fmt(v, kind="f"):
    if v is None: return "n/a"
    if kind == "p": return f"{v:.3f}"
    if kind == "k": return f"{v/1000:.0f}k"
    if kind == "$": return f"{v:.3f}"
    return f"{v:.1f}"

wo, wi = agg(cells["without"]), agg(cells["with"])
# infra?
infra = []
for side in ("without", "with"):
    for kind in ("infra", "incompatible"):
        p = Path(f"results/ab/{pr}/{side}.{kind}.json")
        if p.exists():
            try:
                infra.append(f"{side}.{kind}: {json.load(open(p)).get('reason','')[:180]}")
            except Exception as e:
                infra.append(f"{side}.{kind}: unreadable ({e})")

tc = {}
for side in ("without", "with"):
    p = Path(f"results/ab/{pr}/{side}.toolchain.json")
    if p.exists():
        try: tc[side] = json.load(open(p))
        except Exception: tc[side] = {}

spend = float(os.popen(f"python3 {repr('$S')} total".replace("'$S'","results/ab-logs/setaside_stats.py")).read().strip() or "0")

# CR count from log
import subprocess
log = f"results/ab-logs/enont-{pr}.log"
cr = 0
try:
    out = subprocess.check_output(["rg", "-c", "ConnectionResetError", log], text=True).strip()
    cr = int(out or 0)
except Exception:
    cr = 0

lines = []
lines.append(f"ENOENT-set PR #{pr} done ({status}) @ 019ad6e / PR #8")
lines.append("")
if infra:
    lines.append("INFRA/INCOMPATIBLE:")
    for i in infra: lines.append(f"- {i}")
    lines.append("")
if wo and wi:
    def delta(a,b):
        if a is None or b is None or a == 0: return "n/a"
        return f"{(b-a)/a*100:+.1f}%"
    lines.append("Researcher scoring lock (report only — do NOT claim clear for mid-era rows):")
    lines.append(f"- Primary: pass {fmt(wo['pass'],'p')}→{fmt(wi['pass'],'p')}; wall {fmt(wo['wall'])}→{fmt(wi['wall'])}s ({delta(wo['wall'],wi['wall'])}); out_tok {fmt(wo['out'])}→{fmt(wi['out'])}; non-cache input {fmt(wo['nonc'])}→{fmt(wi['nonc'])} (proxy_in {fmt(wo['pin'])}→{fmt(wi['pin'])})")
    lines.append(f"- Tokens total/cell: {fmt(wo['tok'],'k')}→{fmt(wi['tok'],'k')} ({delta(wo['tok'],wi['tok'])})")
    lines.append(f"- $ secondary: $/cell {fmt(wo['cost'],'$')}→{fmt(wi['cost'],'$')} ({delta(wo['cost'],wi['cost'])}); PR$ ~{(wo['cost'] or 0)*wo['n']+(wi['cost'] or 0)*wi['n']:.2f}")
    # bucket table if tok/$ diverge
    if wo['tok'] and wi['tok'] and wo['cost'] and wi['cost'] and wo['tok']>0 and wo['cost']>0:
        tok_d = (wi['tok']-wo['tok'])/wo['tok']*100
        cost_d = (wi['cost']-wo['cost'])/wo['cost']*100
        if abs(tok_d - cost_d) > 5:
            lines.append(f"- FLAG tok vs $ diverge: tok Δ {tok_d:+.1f}% vs cost Δ {cost_d:+.1f}% (gap {abs(tok_d-cost_d):.1f}pp)")
            lines.append("")
            lines.append("| side | n | pass | wall_s | out_tok | noncache_in | tok/cell | $/cell |")
            lines.append("|---|---|---|---|---|---|---|---|")
            for name,s in (("without",wo),("with",wi)):
                lines.append(f"| {name} | {s['n']} | {fmt(s['pass'],'p')} | {fmt(s['wall'])} | {fmt(s['out'])} | {fmt(s['nonc'])} | {fmt(s['tok'],'k')} | {fmt(s['cost'],'$')} |")
    lines.append(f"- Metering: proxy={wo['pbase']}/{wi['pbase']}; classes={wo['fc']}/{wi['fc']}; unmetered={wo['unmetered']}/{wi['unmetered']}")
elif wo or wi:
    s = wo or wi
    name = "without" if wo else "with"
    lines.append(f"Partial: only {name} scored n={s['n']} pass={fmt(s['pass'],'p')}")
else:
    lines.append("No scored cells.")
lines.append(f"- CR={cr}; toolchain without={tc.get('without')} with={tc.get('with')}")
lines.append(f"- cumulative spend est. \${spend:.2f} (soft pause \$700)")
lines.append(f"- paths: results/ab/{pr}/ ; log results/ab-logs/enont-{pr}.log")
text = "\n".join(lines) + "\n"
Path(f"results/ab-logs/enont-posts/pr-{pr}-group.md").write_text(text)
# also append progress
with open("results/ab-logs/enont-progress.md", "a") as fh:
    fh.write(f"\n## PR {pr} ({status})\n")
    fh.write(text)
    fh.write("\n")
print(text)
PY
}

for pr in $PRS; do
  spent=$(python3 $S total)
  if python3 -c "import sys; sys.exit(0 if float('$spent') + $HEADROOM > $CAP else 1)"; then
    msg="SOFT PAUSE before $pr: spend \$$spent + headroom \$$HEADROOM > cap \$$CAP"
    echo "$msg" | tee -a "$LOG"
    echo -e "\n**SOFT PAUSE before PR $pr: spend \$$spent near \$$CAP**" >> "$PROGRESS"
    echo "$msg" > "$LATEST"
    printf '%s\n' "$msg" > "$POSTDIR/pause-group.md"
    break
  fi
  echo "=== PR $pr start $(date -Is) spend=\$$spent" | tee -a "$LOG"
  echo "PR $pr running (spend=\$$spent)" > "$LATEST"
  setsid python3 -m thesis.ab.run_ab "$FIXTURE" --pr "$pr" --trials 3 --jobs 8 \
    --out results/ab --cache "$CACHE" \
    > "results/ab-logs/enont-$pr.log" 2>&1 &
  rp=$!
  killed=0
  while kill -0 $rp 2>/dev/null; do
    sleep 30
    s=$(python3 $S total)
    if python3 -c "import sys; sys.exit(0 if float('$s') > $CAP else 1)"; then
      echo "CAP HIT during $pr: \$$s; killing runner group $rp" | tee -a "$LOG"
      kill -- -$rp 2>/dev/null
      sleep 5
      kill -9 -- -$rp 2>/dev/null
      killed=1
      break
    fi
  done
  wait $rp 2>/dev/null
  rc=$?
  echo "=== PR $pr exit $rc $(date -Is) spend=\$$(python3 $S total)" | tee -a "$LOG"
  {
    echo "--- signals ---"
    rg -c 'ConnectionResetError' "results/ab-logs/enont-$pr.log" 2>/dev/null | awk '{print "ConnectionResetError_count="$1}'
    rg -c 'ENOENT|No such file or directory' "results/ab-logs/enont-$pr.log" 2>/dev/null | awk '{print "ENOENTish_count="$1}'
    grep -E "launched|incompatible|infra|proxy_measured|musl" "results/ab-logs/enont-$pr.log" 2>/dev/null | sort | uniq -c | head -20
  } | tee -a "$LOG" || true
  status="exit $rc, $(date '+%H:%M ET')"
  [ "$killed" = 1 ] && status="KILLED at cap"
  post_pr "$pr" "$status"
  echo "PR $pr done rc=$rc spend=\$$(python3 $S total)" > "$LATEST"
  [ "$killed" = 1 ] && break
done

echo "ENONT END $(date -Is) spend=\$$(python3 $S total)" | tee -a "$LOG"

# final report
python3 - <<'PY'
import glob, json, statistics as st, os, subprocess
from pathlib import Path
from datetime import datetime
from thesis.ab.summarize import row_cost

prs = [4204, 5066, 5131, 5140, 5527, 6524]
# include 4838 smoke in report
all_prs = [4838] + prs

def total():
    t=0.0
    for p in glob.glob('results/ab/*/cells/*/*/*.json'):
        try:
            c=row_cost(json.load(open(p)))
        except Exception:
            c=None
        t += c or 0
    return t

def side_stats(pr, side):
    for kind in ('infra','incompatible'):
        p=f'results/ab/{pr}/{side}.{kind}.json'
        if os.path.exists(p):
            try:
                d=json.load(open(p))
                return {'bad': True, 'kind': kind, 'reason': (d.get('reason') or '')[:160]}
            except Exception:
                return {'bad': True, 'kind': kind, 'reason': 'unreadable'}
    rows=[]
    for p in glob.glob(f'results/ab/{pr}/cells/{side}/*/*.json'):
        try: rows.append(json.load(open(p)))
        except Exception: pass
    if not rows:
        return {'bad': True, 'kind': 'empty', 'reason': 'no cells'}
    n=len(rows)
    passr=sum(1 for x in rows if x.get('success'))/n
    walls=[x['wall_time_s'] for x in rows if x.get('wall_time_s') is not None]
    toks=[]; outs=[]; nonc=[]; costs=[]
    pbase={}
    for x in rows:
        if x.get('tokens_output') is not None:
            toks.append((x.get('tokens_input_uncached') or 0)+(x.get('tokens_output') or 0)+(x.get('tokens_cache_read') or 0)+(x.get('tokens_cache_write') or 0))
            outs.append(x.get('tokens_output') or 0)
            nonc.append(x.get('tokens_input_uncached') or 0)
        c=row_cost(x)
        if c is not None: costs.append(c)
        k=x.get('token_basis_proxy') or x.get('token_basis')
        pbase[k]=pbase.get(k,0)+1
    return {
        'bad': False, 'n': n, 'pass': passr,
        'wall': st.mean(walls) if walls else None,
        'tok': st.mean(toks) if toks else None,
        'out': st.mean(outs) if outs else None,
        'nonc': st.mean(nonc) if nonc else None,
        'cost': st.mean(costs) if costs else None,
        'pbase': pbase,
        'unmetered': n-len(costs),
    }

lines=[]
lines.append('# ENOENT-set report @ 019ad6e / PR #8 packaging')
lines.append('')
lines.append(f'Generated {datetime.now().isoformat(timespec="seconds")}. Soft CAP=$700.')
lines.append('Smoke #4838 first (PASS), then 4204/5066/5131/5140/5527/6524. Did not run 913/984/1248/3369/3418. Did not restart hard5. Did not merge git.')
lines.append(f'Worktree HEAD: `{subprocess.check_output(["git","rev-parse","--short","HEAD"], text=True).strip()}`')
lines.append(f'Cumulative est. spend: **${total():.2f}**')
lines.append('')
lines.append('| PR | n (b/a) | Pass b→a | Wall s b→a | Out tok b→a | Noncache in b→a | Tok/cell b→a | $/cell b→a | Meter | Notes |')
lines.append('|---|---|---|---|---|---|---|---|---|---|')
for pr in all_prs:
    wo=side_stats(pr,'without'); wi=side_stats(pr,'with')
    if wo.get('bad') or wi.get('bad'):
        note=[]
        if wo.get('bad'): note.append(f"without:{wo['kind']} {wo['reason'][:80]}")
        if wi.get('bad'): note.append(f"with:{wi['kind']} {wi['reason'][:80]}")
        lines.append(f'| {pr} | — | — | — | — | — | — | — | — | {"; ".join(note)} |')
        continue
    def dlt(a,b,pct=True):
        if a is None or b is None: return 'n/a'
        if not pct: return f'{a:.1f}→{b:.1f}'
        if a==0: return f'{a:.1f}→{b:.1f}'
        return f'{a:.1f}→{b:.1f} ({(b-a)/a*100:+.1f}%)'
    def dltp(a,b):
        return f'{a:.3f}→{b:.3f}'
    def dltk(a,b):
        if a is None or b is None: return 'n/a'
        pct = (b-a)/a*100 if a else 0
        return f'{a/1000:.0f}k→{b/1000:.0f}k ({pct:+.1f}%)'
    def dlt$(a,b):
        if a is None or b is None: return 'n/a'
        pct = (b-a)/a*100 if a else 0
        return f'{a:.3f}→{b:.3f} ({pct:+.1f}%)'
    meter=f"{wo['pbase']}/{wi['pbase']}"
    note=''
    if wo['unmetered'] or wi['unmetered']:
        note=f"UNMETERED {wo['unmetered']}/{wi['unmetered']}"
    # CR
    log=f'results/ab-logs/enont-{pr}.log' if pr!=4838 else 'results/ab-logs/smoke-4838.run.log'
    cr=0
    try:
        cr=int(subprocess.check_output(['rg','-c','ConnectionResetError',log], text=True).strip() or 0)
    except Exception:
        cr=0
    if cr: note=(note+'; ' if note else '')+f'CR={cr}'
    lines.append(f"| {pr} | {wo['n']}/{wi['n']} | {dltp(wo['pass'],wi['pass'])} | {dlt(wo['wall'],wi['wall'])} | {dlt(wo['out'],wi['out'])} | {dlt(wo['nonc'],wi['nonc'])} | {dltk(wo['tok'],wi['tok'])} | {dlt$(wo['cost'],wi['cost'])} | {meter} | {note} |")

lines.append('')
lines.append('## Notes')
lines.append('- Researcher scoring lock: primary = pass, wall, output tokens, non-cache input; $ secondary with bucket table when tok/$ diverge. No clear claims for mid-era rows.')
lines.append('- Quarantine: `results/ab-quarantine/pre-enont-<pr>/` and `pre-enont-musl-bins/`.')
lines.append('- Group posts drafted under `results/ab-logs/enont-posts/` (executor lacks SendToAgent; parent should relay to Senior Thesis group `7eed13d4-27d6-4739-acfd-0f1c0d3febc7`).')
lines.append(f'- Latest: see `results/ab-logs/enont-latest.txt` / `enont-progress.md`.')
Path('results/ab-logs/enont-report.md').write_text('\n'.join(lines)+'\n')
print('wrote enont-report.md spend=', f'{total():.2f}')
PY

echo "done spend=\$$(python3 $S total)" > "$LATEST"
echo "ENONT REPORT written $(date -Is)" | tee -a "$LOG"
