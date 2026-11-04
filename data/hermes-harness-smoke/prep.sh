#!/usr/bin/env bash
# One-time VM prep for the Hermes hard-suite arm. Run on the thesis VM, not
# on a dev machine. Installs NousResearch/hermes-agent at the comparison pin
# with Hermes's own installer (pip/uv from git is unsupported upstream),
# pre-installs the anthropic extra (not installed by default; otherwise the
# first model call reaches PyPI), and writes the pin stamp the adapter checks.
#
#   bash data/hermes-harness-smoke/prep.sh            # installs under ~/h1/hermes/<pin>
#   HERMES_ROOT=/opt/hermes bash data/hermes-harness-smoke/prep.sh
#
# Prints the two exports cell.py needs (OBENCH_HERMES_ROOT, OBENCH_HERMES_BIN).
set -euo pipefail

PIN=4dcef215cfe41bd2d02c2d1dad6e257a18101216
ROOT="${HERMES_ROOT:-$HOME/h1/hermes/$PIN}"
SRC="$ROOT/src"
HOME_DIR="$ROOT/home"

case "$ROOT" in
  */results/*|*/data/*|*/results|*/data) echo "refusing to install under results/ or data/: $ROOT" >&2; exit 2 ;;
esac

mkdir -p "$ROOT"
INSTALLER="$ROOT/install.sh"
curl -fsSL "https://raw.githubusercontent.com/NousResearch/hermes-agent/$PIN/scripts/install.sh" -o "$INSTALLER"

# --commit skips the stable-release lookup; the installer fetches uv, Python
# 3.14, Node, ripgrep and ffmpeg into the Hermes home.
bash "$INSTALLER" \
  --commit "$PIN" \
  --non-interactive \
  --skip-browser \
  --skip-computer-use \
  --hermes-home "$HOME_DIR" \
  --dir "$SRC"

HEAD="$(git -C "$SRC" rev-parse HEAD)"
if [ "$HEAD" != "$PIN" ]; then
  echo "installed checkout is $HEAD, expected $PIN" >&2
  exit 1
fi

BIN=""
for candidate in "$SRC/.venv/bin/hermes" "$HOME_DIR/bin/hermes" "$HOME/.local/bin/hermes"; do
  if [ -x "$candidate" ]; then BIN="$candidate"; break; fi
done
if [ -z "$BIN" ]; then
  echo "could not find the hermes launcher under $SRC or $HOME_DIR; set OBENCH_HERMES_BIN by hand" >&2
  exit 1
fi

HERMES_HOME="$HOME_DIR" "$BIN" pm install --extra anthropic

printf '%s\n' "$PIN" > "$ROOT/PIN"
echo "hermes $PIN installed (MIT)"
echo "export OBENCH_HERMES_ROOT=$ROOT"
echo "export OBENCH_HERMES_BIN=$BIN"
