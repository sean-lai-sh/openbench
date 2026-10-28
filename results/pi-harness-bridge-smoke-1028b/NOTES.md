# PR #134 bridge smoke rerun, 2026-10-28 (VM thesis-h1-cpu)

Head c001fe7c80b6166c2d3fbb875564b755444cb0e6, image h1-env:1027-strace (sha256:2506cd37...), Vertex model claude-sonnet-5-5.
Spend: $0. No request reached the proxy. Previous run: #178.

## Unit tests
`python3 -m unittest obench.tests.test_proxy_bridge -v`: 16 tests, OK (pr134b-unittest.out).

## Pi cell e1d9987961845ee4
- network_mode: bridge; proxy-bridge 172.17.0.1:41197
- `egress api.anthropic.com blocked (blocked sinkhole 0.0.0.0)`
- `proxy-reached cell=e1d9987961845ee4 reached=no calls=0`
- proxy_observed: [] (no thinking settings); failure_class infra, t_agent 1.0s
- Bug: `obench/adapters/pi_harness.py:435` `_pi_module()` runs `from obench.adapters import pi`; `obench` is not mounted
  (docker_exec.py:710 mounts only adapters_dir at /bench/adapters). The fallback at :437-440 looks up
  `sys.modules["bench_adapter_pi"]`, which is absent, so it re-raises `ModuleNotFoundError: No module named 'obench'`.
  Called from pi_harness.py:497 via adapters/pi.py:1147.

## OpenCode cell eef70fa3fa8168de (sha ba54cee55e18b47fb70badc84ae2cbac7c83d258, the pin used in data/pr128-smoke-1024)
- network_mode: bridge; proxy-bridge 172.17.0.1:41937; Node 20.19.2 at ~/h1/toolchain/node-v20.19.2-linux-x64 (already present)
- `egress api.anthropic.com blocked (blocked sinkhole 0.0.0.0)`
- `proxy-reached cell=eef70fa3fa8168de reached=no calls=0`
- proxy_observed: []; failure_class infra, t_agent 3.8s
- Bug: `obench/adapters/opencode.py:1993` `from thesis.ab.provider_pin import ProviderPinMismatch`; `thesis` is not mounted in the container.
