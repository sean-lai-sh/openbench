import json,glob,sys,collections
F=["pin_source_class","installed_anthropic","lockfile_sha256","opencode_cache","load_proof_basis","loaded_anthropic","provider_loaded_source","provider_loaded_version","provider_version_source","provider_versions","sdk_drift","failure_class","error"]
for pat in sys.argv[1:]:
  for f in sorted(glob.glob(pat)):
    d=json.load(open(f)); r={k:d.get(k) for k in F}
    # per-request signals
    ex={k:v for k,v in d.items() if any(s in k.lower() for s in ("user_agent","ua_","loaded_anthropic_","per_request","requests_loaded","http_status","retry","429","timeout","infra")) and k not in F}
    print(json.dumps({"row":"/".join(f.split("/")[-7:]),**r,"other":ex},default=str)[:1500])
