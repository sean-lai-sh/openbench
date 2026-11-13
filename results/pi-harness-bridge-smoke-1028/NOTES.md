# PR #134 bridge smoke, 2026-10-28 (VM thesis-h1-cpu)

Head c0549bcc337259d8ccc3b07ef445842b0909fe87, image h1-env:1027-strace, model claude-sonnet-5-5. Spend: $0 (no request reached Vertex).

## Unit test
`python3 -m unittest obench.tests.test_proxy_bridge.BridgeContainerTests -v`: 1 test, OK (pr134-unittest.out).

## Pi cell (bridge, shared forwarder 172.17.0.1:32923), cell 08d29ed1ff3d02b0
- network_mode: bridge (`OBENCH_DOCKER_NETWORK=bridge`, `--add-host=api.anthropic.com:0.0.0.0`)
- `egress api.anthropic.com blocked (blocked sinkhole 0.0.0.0)`
- `proxy-reached cell=08d29ed1ff3d02b0 reached=no calls=0`
- failure_class infra. In the container `obench/adapters/pi_harness.py:103 rewrite_loopback` imports
  `thesis.ab.proxy_bridge`, and `thesis` is not mounted: `ModuleNotFoundError: No module named 'thesis'`.
  The agent never started, so there are no thinking settings and the ledger is empty.
- Next problem: the cached wrapper `~/h1/pi-src/bin/pi/d0aa.../pi` runs `/opt/node-v22.19.0/bin/node /h1/pi-src/...`.
  It was built inside the container, but the bridge cell mounts the cache at `/home/box/h1/pi-src` and PI_NODE_PREFIX at
  `/home/box/h1/toolchain/node-v22.19.0-linux-x64`. That would fail even after the import fix.
- The run used PI_NODE_PREFIX=~/h1/toolchain/node-v22.19.0-linux-x64, which I downloaded today, and chowned ~/h1/pi-src (the files were root-owned).

## OpenCode cell: not run
- There is no single-cell bridge entry point. A host-side `run_ab --exec docker` passes no docker_image (the task has none), and
  h1-env:1027-strace has no opencode or node on PATH. The cached wrappers in ~/h1/opencode-src also hard-code container paths under `/h1/...`.
- No egress or proxy-reached lines.
