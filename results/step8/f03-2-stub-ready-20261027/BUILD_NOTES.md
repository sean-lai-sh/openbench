# Step-8 F03-2 rebuild notes (2026-10-27)

| PR | side | sha | build_channel | version | binary sha256 | lockfile sha256 |
|---|---|---|---|---|---|---|
| 3481 | without | 51e4c9fc | local | 0.0.0-local-202610270426 | 53736f4b… | 157e8ed0… |
| 3481 | with | c1ada302 | local | 0.0.0-local-202610270426 | 11ebac8b… | 157e8ed0… |

Full hashes: `s8-3481local/builds.jsonl` and `s8-3481local/bin/*/build-stamp.json`.

**Why the local channel:** 3481/with built on the default (empty) channel produced the version `0.0.0--<ts>`. At startup, config.ts then ran `bun add @opencode-ai/plugin@0.0.0--<ts>`, which doesn't exist, and the provider was "not listed". With `OPENCODE_CHANNEL=local`, `Installation.isLocal()` skips that install. Both sides are built this way so they stay symmetric. Local also enables dev mode and the DEBUG log level in both. Every other PR keeps `build_channel=default`.

**Result:** both 3481 sides are ready (pin 2.0.0, strace probe loaded 2.0.0). 3481 is **not excluded**.

**Before relaunch:** copy the two local binaries over `~/s8f032/bin/<sha>`. The launcher drops 3481 if either stamp isn't `local`.

**Cell image:** `h1-env:1027-strace` (sha256:2506cd378b60c27f3bc40844564b1665647306ed65fa4c20b99391d04d5a0462) = `h1-env:1022` + apt strace 6.1 (see `img1027/Dockerfile`).

## Egress backstop (round 3, 2026-10-27)

`thesis/ab/launchers/egress_block.sh`, sourced by `step8_f032.sh` for the whole run:

* Host: for every address `getent ahosts api.anthropic.com` returns, insert
  `iptables|ip6tables -I OUTPUT 1 -d <ip> -m comment --comment obench-s8-egress -j REJECT`
  (`icmp-admin-prohibited` / `icmp6-adm-prohibited`). Cells run `--network host`,
  so container traffic leaves via the host OUTPUT chain (no DOCKER-USER rule needed).
  Resolved on 2026-10-27: 160.79.104.10, 2607:6bc0::10.
* Container: `--add-host api.anthropic.com:0.0.0.0` (DNS/hosts sinkhole).
* Launch-time check (`egress_verify $IMG`): curl to https://api.anthropic.com/v1/models must fail
  from the host, by direct IP (`--resolve`, proves the iptables rule rather than DNS), and from a
  container started like a cell. Any success aborts before a cell runs.
* `trap egress_remove EXIT` deletes every rule carrying the `obench-s8-egress` tag.
* VM-local only; no GCP firewall or IAM change.
* Verified on thesis-h1-cpu: see results/step8/f03-2-route-20261027/r3/egress.txt.
