import json,glob,sys
for f in sorted(glob.glob(sys.argv[1]+"/*/*/cells/*/*/*.json")):
    d=json.load(open(f)); cm=d.get("cell_meta") or {}
    print(f.split(sys.argv[1])[1], d.get("failure_class"), d.get("success"), round(d.get("requests_cost_usd") or 0,3), d.get("loaded_anthropic"), d.get("provider_loaded_source"), "vm=",d.get("vm_name") or cm.get("vm_name"), "iid=",d.get("instance_id") or cm.get("instance_id"), (d.get("failure_reason") or "")[:70])
