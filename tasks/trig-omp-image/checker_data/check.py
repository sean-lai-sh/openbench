import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import verdict, entry


def top(text, key):
    vals = re.findall(rf"^{key}\s*:\s*[\"']?(\d+)[\"']?\s*(?:#.*)?$", text, re.M)
    return vals


def main():
    p = Path("config.yaml")
    if not p.exists():
        return verdict(False, "config.yaml missing")
    text = p.read_text(encoding="utf-8")
    port, admin = top(text, "port"), top(text, "admin_port")
    if port != ["8443"] or admin != ["9000"]:
        return verdict(False, f"port={port} admin_port={admin}; want port 8443, admin_port 9000")
    return verdict(True, "port 8443, admin_port unchanged")


if __name__ == "__main__":
    entry(main)
