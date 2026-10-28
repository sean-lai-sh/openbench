#!/bin/bash
# One Pi smoke cell per model (claude-opus-5-5, claude-sonnet-5-5) on
# polyglot-rust-c. Builds pin d0aa218cb16c333c008f6aa3dcd670ac8b68383c and
# routes Anthropic /v1/messages through the Vertex proxy. Does not set
# OBENCH_PI_VERTEX. Needs GOOGLE_CLOUD_PROJECT and ADC. Smoke output is not
# a scored campaign.
#
# pip install -e /ob only installs obench*, so thesis is imported from the
# checkout via PYTHONPATH. h2-env:1022 has no nvm or Node; this script
# downloads Node 22.19.0 (the engines.node floor at the Pi pin) and leaves a
# tiny $HOME/.nvm/nvm.sh so thesis.ab.toolchain.ensure_node can resolve it.
# The shared image is not modified.
set -u
export OBENCH_HARBOR_APP_REWRITE=1
export PYTHONPATH="/ob${PYTHONPATH:+:$PYTHONPATH}"
git config --global --add safe.directory "*"
python3 -m venv /venv && /venv/bin/pip install -q -e /ob

# Pi d0aa218 package.json: "engines": {"node": ">=22.19.0"}.
NODE_VERSION=22.19.0
case "$(uname -m)" in
  x86_64)
    NODE_ARCH=x64
    NODE_SHA256=d36e56998220085782c0ca965f9d51b7726335aed2f5fc7321c6c0ad233aa96d
    ;;
  aarch64|arm64)
    NODE_ARCH=arm64
    NODE_SHA256=d32817b937219b8f131a28546035183d79e7fd17a86e38ccb8772901a7cd9009
    ;;
  *)
    echo "preflight: unsupported architecture $(uname -m)" >&2
    exit 1
    ;;
esac
if [ -n "${PI_NODE_PREFIX:-}" ]; then
  NODE_PREFIX=$PI_NODE_PREFIX
elif mkdir -p /opt 2>/dev/null && [ -w /opt ]; then
  NODE_PREFIX=/opt/node-v${NODE_VERSION}
else
  NODE_PREFIX=${HOME}/.local/node-v${NODE_VERSION}
fi
if ! "$NODE_PREFIX/bin/node" --version 2>/dev/null | grep -qx "v${NODE_VERSION}"; then
  tarball="node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.gz"
  tmp=$(mktemp -d)
  curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/${tarball}" -o "${tmp}/${tarball}"
  python3 - "$NODE_SHA256" "${tmp}/${tarball}" <<'PY'
import hashlib, sys
want, path = sys.argv[1], sys.argv[2]
got = hashlib.sha256(open(path, "rb").read()).hexdigest()
if got != want:
    raise SystemExit(f"node tarball checksum {got} != {want}")
PY
  mkdir -p "$(dirname "$NODE_PREFIX")"
  rm -rf "$NODE_PREFIX"
  tar -xzf "${tmp}/${tarball}" -C "$(dirname "$NODE_PREFIX")"
  mv "$(dirname "$NODE_PREFIX")/node-v${NODE_VERSION}-linux-${NODE_ARCH}" "$NODE_PREFIX"
  rm -rf "$tmp"
fi
export PATH="${NODE_PREFIX}/bin:${PATH}"

# ensure_node shells out to nvm. Point that at the Node we just unpacked.
NVM_DIR="${NVM_DIR:-${HOME}/.nvm}"
export NVM_DIR
mkdir -p "$NVM_DIR"
cat > "${NVM_DIR}/nvm.sh" <<EOF
nvm() {
  case "\${1:-}" in
    install) return 0 ;;
    which) printf '%s\n' '${NODE_PREFIX}/bin/node' ;;
    *) return 0 ;;
  esac
}
EOF

# Cheap preflight before cell.py, which is what starts model calls.
if ! /venv/bin/python -c "import thesis"; then
  echo "preflight: import thesis failed" >&2
  exit 1
fi
if ! node --version; then
  echo "preflight: node --version failed" >&2
  exit 1
fi

OUT="${1:-/h2/pi-harness-smoke}"
mkdir -p "$OUT"
cd /ob && /venv/bin/python data/pi-harness-smoke/cell.py --out "$OUT" ${PI_SMOKE_MODELS:+--models "$PI_SMOKE_MODELS"} \
  > "$OUT/run.log" 2>&1
echo EXIT $? >> "$OUT/run.log"
