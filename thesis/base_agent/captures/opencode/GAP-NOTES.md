# OpenCode AC3 gap: base vs real (capture fad5203d, ba54cee5 on thesis-h1-cpu)
Measured by diffing the first main-loop request of each side (gate replay, parity arm).

## Now: system 8673 / 8673 (0%), tools 35967 / 35967 (0%)

## History
### System bytes: was base 8557, real 8673 (-1.34%, gap 116 bytes)
The entire gap was OpenCode's Anthropic identity header, which the base config used to leave out:
- real system block 1 (57 bytes): `You are Claude Code, Anthropic's official CLI for Claude.`
- real system block 2 starts with the same line plus a blank line (59 bytes), then the body.
- After those lines the rest of the system text was byte-identical to the base (8557 = 8616 - 59).

Fixed: the config now sends the header the way ba54cee5 does (sst/opencode ba54cee5:
packages/opencode/src/session/prompt/anthropic_spoof.txt via session/system.ts header() and
session/llm.ts): its own cached block, then the prefix of the main block. Vendored as
`assets/opencode/anthropic_spoof.txt` and switched on by `[modules.M1] params.header`; M3 now marks both
system blocks, as the real build does. `test_stage4_harness_configs.ClaudeCodeIdentityAllowlist` allows the
exact line only in that asset and this capture directory, and checks it appears nowhere else.

### Tool bytes: was base 36071, real 35967 (+0.29%, gap 104 bytes)
The entire gap was in the `bash` tool: `assets/opencode/tools.json` carried the Mac capture's workdir
(76 chars) where the replay uses its own (24 chars), twice: 2 x 52 = 104 bytes.
Fixed by c99c84949d (Fill OpenCode's working directory into its captured bash tool spec): the base fills
the run's cwd into the captured bash spec, so tool bytes now match exactly.
