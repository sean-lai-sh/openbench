# Pre-registered Opus check sample (drawn 2026-10-16 before any 447-screen results).
# Pool: included=yes and not in the earlier 34 (those get Opus anyway). Stratified by exercisable,
# proportional allocation of 50 (largest remainder). Shuffle each stratum with SEED, take first k, then
# interleave into one draw order by a seeded shuffle. Rule: PRs that later show a Sonnet signal go to Opus
# anyway; the first 40 in draw_order with no Sonnet signal form the check sample.
import csv, random, hashlib
SEED = 20261016; N = 50
rows = [r for r in csv.DictReader(open('opencode-harness-prs-full.csv')) if r['included']=='yes' and r['in_earlier_34']=='no']
rows.sort(key=lambda r:int(r['pr']))
strata = {}
for r in rows: strata.setdefault(r['exercisable'], []).append(r)
tot = len(rows); quota = {k: N*len(v)//tot for k,v in strata.items()}
rem = sorted(strata, key=lambda k: -(N*len(strata[k])/tot - quota[k]))
for k in rem[:N-sum(quota.values())]: quota[k]+=1
rng = random.Random(SEED); picked=[]
for k in sorted(strata):
    s = strata[k][:]; rng.shuffle(s); picked += s[:quota[k]]
rng.shuffle(picked)
with open('opus-check-sample.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['draw_order','pr','exercisable','trigger_task','title','merge_sha'])
    for i,r in enumerate(picked,1): w.writerow([i,r['pr'],r['exercisable'],r['trigger_task'],r['title'],r['merge_sha']])
print(tot, {k:len(v) for k,v in strata.items()}, quota)
print(hashlib.sha256(open('opus-check-sample.csv','rb').read()).hexdigest())
