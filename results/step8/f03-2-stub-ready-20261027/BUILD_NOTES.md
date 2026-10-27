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
