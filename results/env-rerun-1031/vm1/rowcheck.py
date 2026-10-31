import json,glob,collections,sys
c=collections.Counter()
for root in sys.argv[1:]:
  for f in glob.glob(root+"/*/*/cells/*/*/*.json"):
    try: d=json.load(open(f))
    except Exception: continue
    c[(root.split("/")[-1],f.split("/")[-6] if False else f[len(root)+1:].split("/")[0],d.get("loaded_anthropic"),d.get("failure_class") or d.get("status"),d.get("vm_name"),d.get("runner_commit","")[:8])]+=1
for k,v in sorted(c.items(),key=str): print(v,*k)
