Quarantined phase 2 data (runner bugs, not harness results). Moved, not deleted.
- decimalerror-<pr> (3052, 3115, 3369, 3418; v0.14.7-v0.15.17): opencode dies after the first model step with
  "Error: [DecimalError] Invalid argument: [object Object]" (cost calc on usage object); cells have no tokens and score ~0. Invalid.
- musl-binary-<pr> (4204, 4838, 5066, 5131, 5140, 5527, 6524; v1.0.79-v1.0.221): build_opencode._find_binary picks sorted()[-1]
  of dist/**/bin/opencode = opencode-linux-x64-musl (or -baseline-musl); on this glibc box exec fails ENOENT, so compat marks
  "not listed while loading anthropic/claude-opus-5-5". False incompatibility.
