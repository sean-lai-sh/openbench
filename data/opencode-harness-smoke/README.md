# OpenCode bridge smoke

One cell on `polyglot-rust-c` through the same Vertex proxy path as
`data/pi-harness-smoke/cell.py`. The proxy listens on `127.0.0.1`. A forwarder
on the docker bridge gateway accepts the container. The cell network is
`bridge` (do not pass `--network host`). The egress probe re-resolves
`api.anthropic.com` inside that network and logs the sinkhole. It does not
send an HTTP request to Anthropic.

`h1-env:1027-strace` has no `opencode` and no Node. The cache is mounted at
`/h1/opencode-src` and `OPENCODE_NODE_PREFIX` at its `/h1/...` path, matching
the cached wrappers.

The adapter alias is `claude-opus-5-5` (that is the proxy route).
`--vertex-model` is what the proxy calls. Each cell record stores
`network_mode` and `proxy_observed` (thinking mode, thinking field, and
reasoning tokens the proxy saw). An empty ledger is an empty list.

`python3 -m thesis.ab.run_ab --exec docker` passes `--image` (or
`OBENCH_CELL_IMAGE`) through to `run_cell` as `docker_image`. A task that
declares its own image still wins.

```bash
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:?}"
export OBENCH_CELL_IMAGE="${OBENCH_CELL_IMAGE:-h1-env:1027-strace}"
export OPENCODE_SHA="${OPENCODE_SHA:?}"
export OPENCODE_NODE_PREFIX="${OPENCODE_NODE_PREFIX:-$HOME/h1/toolchain/node-v20.19.2-linux-x64}"
python3 data/opencode-harness-smoke/cell.py \
  --out "${HOME}/opencode-harness-smoke-bridge" \
  --exec docker \
  --image "$OBENCH_CELL_IMAGE" \
  --cache "${OPENCODE_HARNESS_CACHE:-$HOME/h1/opencode-src}" \
  --sha "$OPENCODE_SHA" \
  --node "$OPENCODE_NODE_PREFIX" \
  --vertex-model claude-sonnet-5-5
```

Stdout and `<out>/smoke.log` each get:

- `egress api.anthropic.com blocked (...)` before the cell. `REACHABLE` exits 1 and does not start the cell.
- `proxy-reached cell=<id> reached=yes calls=<n>` after the cell, when a request arrived at the proxy.
