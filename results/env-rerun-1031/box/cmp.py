import json,sys
d=json.load(open(sys.argv[1]))
for k,v in sorted(d.items()):
  if any(s in k.lower() for s in ("anthropic","provider","manifest","lock","cache","sdk","installed")): print(k,str(v)[:160])
