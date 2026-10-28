#!/usr/bin/env python3
"""Classify step-8 infra/hang cells per @ai-sdk/anthropic version (read-only).
Order: AUTH, INST (install), PROV (provider fault), TIME (timeout), else other.
Text = error, infra_reason, provider_error, requests_error, hang_reason, output_tail.
Cells with no recorded version: log_installed = last "installed @ai-sdk/anthropic@X"
in the cell text, spec_seen = "Unsupported model version vN" (the loaded provider spec).
Non-infra cells that hit "Unhandled chunk type" are kept too (failure_class shows it).
Writes results/step8-pins-D4/provider_faults.csv. Run from repo root."""
import json,glob,re,csv,collections
AUTH=re.compile(r"authentication_error|invalid x-api-key",re.I)
INST=re.compile(r"bun\W+add|NpmInstallFailedError|No matching version found",re.I)
PROV=re.compile(r"Unhandled chunk type|AI_\w*Error|APICallError|TypeValidationError|stream error|overloaded_error|api_error|invalid_request_error",re.I)
TIME=re.compile(r"no_progress|idle_s|timed out|timeout|ETIMEDOUT|ECONNRESET|Connection",re.I)
INSTALLED=re.compile(r"installed @ai-sdk/anthropic@(\S+)")
SPEC=re.compile(r"Unsupported model version (v\d+)")
VERS={"2.0.0","2.0.0-beta.11","2.0.0-beta.13","3.0.64","3.0.71"}
rows=[];tot=collections.Counter()
for f in sorted(glob.glob('results/step8-*/**/*.jsonl',recursive=True)):
  if '/transcripts/' in f or 'proxy-ledger' in f: continue
  for i,l in enumerate(open(f)):
    try:d=json.loads(l)
    except:continue
    if 'cell_seed' not in d: continue
    v=(d.get('provider_versions') or {}).get('@ai-sdk/anthropic') or (d.get('toolchain') or {}).get('anthropic')
    fc=d.get('failure_class')
    if v is None: v='unrecorded'
    txt0=" | ".join(str(d.get(k)) for k in ('error','infra_reason','provider_error','requests_error','hang_reason','output_tail') if d.get(k))
    chunk_other=fc not in ('infra','hang') and 'Unhandled chunk type' in txt0  # e.g. wrong_answer cells that also hit a chunk error
    if (v not in VERS and v!='unrecorded') or (fc not in ('infra','hang') and not chunk_other): continue
    txt=" | ".join(str(d.get(k)) for k in ('error','infra_reason','provider_error','requests_error','hang_reason','output_tail') if d.get(k))
    m=None
    if AUTH.search(txt): cls='other:auth'; m=AUTH.search(txt)
    elif INST.search(txt): cls='other:install'; m=INST.search(txt)
    elif PROV.search(txt): cls='provider_fault'; m=PROV.search(txt)
    elif TIME.search(txt): cls='timeout'; m=TIME.search(txt)
    else: cls='other'
    cls=cls
    snip=(txt[max(0,m.start()-60):m.end()+100] if m else txt[:160]).replace('\n',' ')
    li=INSTALLED.findall(txt); sp=SPEC.search(txt)
    rows.append(dict(version=v,log_installed=li[-1] if li else '',spec_seen=sp.group(1) if sp else '',failure_class=fc,classification=cls,file=f,line=i+1,task=d.get('task'),trial=d.get('trial'),run_id=d.get('run_id'),snippet=snip))
w=csv.DictWriter(open('results/step8-pins-D4/provider_faults.csv','w',newline=''),fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
c=collections.Counter((r['version'],r['failure_class'],r['classification']) for r in rows)
for k in sorted(c):print(k,c[k])
for r in rows:
  if r['classification']!='timeout':print(r['version'],r['failure_class'],r['classification'],r['file'].split('/')[1],r['file'].split('/')[2],r['task'],r['trial'],'::',r['snippet'][:200])
