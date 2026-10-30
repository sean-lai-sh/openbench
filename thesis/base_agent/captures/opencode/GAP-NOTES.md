# OpenCode AC3 gap: base vs real (capture fad5203d, ba54cee5 on thesis-h1-cpu)

Measured by diffing the first main-loop request of each side (gate replay, parity arm).

## System bytes: base 8557, real 8673 (-1.34%, gap 116 bytes)
The entire gap is OpenCode's Anthropic identity prefix, which the base config leaves out:
- real system block 1 (57 bytes): `You are Claude Code, Anthropic's official CLI for Claude.`
- real system block 2 starts with the same line plus a blank line (59 bytes), then the body.
- After those lines, the rest of the system text is byte-identical to the base (8557 = 8616 - 59).
The base leaves this out deliberately (the #199 test that blocks Claude Code strings). The gap is the size of that exclusion, not drift.

## Tool bytes: base 36071, real 35967 (+0.29%, gap 104 bytes)
The entire gap is in the `bash` tool (base 10694, real 10590). Its description and `workdir` parameter
description embed the cwd twice, and `assets/opencode/tools.json` has the **Mac capture's workdir hardcoded**
(`/private/var/folders/xv/xbhtpy_51sn67gsryt543w5m0000gn/T/stub-ready-_wchqtpl`, 76 chars), not the replayed
workdir (`/tmp/stub-ready-7gakcipo`, 24 chars): 2 x 52 = 104 bytes. All other 10 tools match byte for byte.
Follow-up (not fixed here): template the cwd in tools.json the way the system prompt's cwd is replayed. That
makes the tool bytes exact and stops cell runs carrying a Mac path.
