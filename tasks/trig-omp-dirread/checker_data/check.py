import sys, re, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import verdict, entry

import importlib, os
def main():
    sys.path.insert(0, os.getcwd())
    for m in list(sys.modules):
        if m.startswith("codecs_pkg"): del sys.modules[m]
    plugs = sorted(p.stem for p in Path("codecs_pkg/plugins").glob("*.py") if p.stem != "__init__")
    try:
        reg = importlib.import_module("codecs_pkg.registry")
        loaded = reg.load_all()
    except Exception as e:
        return verdict(False, f"registry failed: {e!r}")
    if "zstd" not in loaded or loaded["zstd"] != "zstd":
        return verdict(False, "zstd codec not registered")
    missing = [p for p in plugs if p not in loaded]
    if missing:
        return verdict(False, "plugins dropped from registry: " + ", ".join(missing))
    if len(plugs) != 17:
        return verdict(False, f"plugin modules added/removed: {len(plugs)}")
    return verdict(True, "all 17 plugins registered including zstd")

if __name__ == "__main__":
    entry(main)
