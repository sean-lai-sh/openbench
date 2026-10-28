# Pi harness-comparison smoke

One local cell per model (`claude-opus-5-5`, `claude-sonnet-5-5`) on
`polyglot-rust-c`, through the Vertex proxy from PR #128. Pi is pinned to
`d0aa218cb16c333c008f6aa3dcd670ac8b68383c` and speaks Anthropic
`POST /v1/messages` (`models.json` `baseUrl` is the cell proxy without `/v1`).
The script builds that git commit. It does not install npm
`@earendil-works/pi-coding-agent@1.4.0` (tag `v1.4.0` is `4a080252`, a
different commit).

```bash
bash data/pi-harness-smoke/cell.sh /h2/pi-harness-smoke
```

Requires `GOOGLE_CLOUD_PROJECT` (or `GCLOUD_PROJECT`). An
`application_default_credentials.json` file is used when it exists. When it
does not, the proxy uses the GCE metadata server (the same path as
`OBENCH_ADC_METADATA=1`) and exits before the cell if that token cannot be
read. The script unsets `OBENCH_PI_VERTEX` so the A/B adapter path
does not run. Cell cap is 2400s. Transcripts stay under the output directory.

Each `<model>.json` holds the `run_cell` row (checker exit included), the
settings sidecar, proxy `totals.json` parsed into `all` / `main` / `side`,
and list-price cost for the all-call and main-only buckets. Smoke outcomes
are not analysed.

## One bridge-network cell

Host-network cells stay on the loopback proxy (`exec` default `local`, or
`--network host`). A bridge cell is a different command. Run it on the VM
host, where the proxy and the Docker daemon share a network namespace. Do
not pass `--network host`. The proxy keeps listening on `127.0.0.1`. A
forwarder on the docker bridge gateway accepts the container, and nothing
else. The cell container sinkholes `api.anthropic.com` to `0.0.0.0`. The
host OUTPUT rules are not changed.

```bash
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:?}"
export OBENCH_CELL_IMAGE="${OBENCH_CELL_IMAGE:-h2-env:1022}"
# Set this when the image has no Node >= 22.19.0. The host directory is
# mounted read-only at /opt/node-v22.19.0, and the cache at /h1/pi-src.
# Those are the paths the cached wrapper execs.
# export PI_NODE_PREFIX="$HOME/h1/toolchain/node-v22.19.0-linux-x64"
python3 data/pi-harness-smoke/cell.py \
  --out "${HOME}/pi-harness-smoke-bridge" \
  --models claude-sonnet-5-5 \
  --exec docker \
  --image "$OBENCH_CELL_IMAGE" \
  --cache "${PI_HARNESS_CACHE:-$HOME/h1/pi-src}"
```

Stdout and `<out>/smoke.log` each get two lines:

- `egress api.anthropic.com blocked (...)` before the cell. `REACHABLE` exits 1 and does not start the cell. The probe resolves the sinkhole name. It does not send an HTTP request to Anthropic.
- `proxy-reached cell=<id> reached=yes calls=<n>` after the cell, when a request arrived at the proxy.

Each cell record includes `network_mode` (`bridge` for this command) and
`proxy_observed`, the thinking mode, thinking field, and reasoning tokens the
proxy recorded for each request. An empty ledger is an empty list.
