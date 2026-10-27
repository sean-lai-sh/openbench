# Step-8 F03-2 pin dry run (2026-10-26, thesis-h1-cpu)

This PR is data only. It made no model calls and launched no F03-2.

- **Builds.** No F03-2 build was found on the box cache, in the backup tgz or on the VM. All 21 F03-2 shas were built fresh on the VM. See `BUILDS.md` for source commits, lockfile sha256, binary sha256 and the control rebuilds.
- **Dry run.** Command: `python3 -m thesis.ab.step8_pin_dry_run --cache /tmp/step8-pin-cache --bin-root ~/s8f032`.
  - F03-2 is 22/22 sides ready (11 with, 11 without) and has 0 loaded-vs-pin mismatches.
  - The loaded check is `unproven` on all 22, because `--version` does not open the provider.
  - The other 566 sides are missing on purpose. Later batches have not been built yet, since sign-off goes batch by batch.
- **Leave-one-out.** `step8_pins apply` was rerun into a scratch dir against a fresh mirror. It gives 114/116 (98.3%), and its pins.csv is identical to main.
