# Provenance

- Source: re-authored 2026-10-16 for the thesis Oh My Pi A/B stage (the original was lost in the box restore).
- Trigger for OMP row 14 (687cf413 vs 3f3e696e): the find tool drops the `path` param and consolidates it into `pattern`. A simple pattern like `*.ts` gets `**/` prepended, making it recursive. Confirmed in the find.ts diff (`parsePatternPath`: "Simple pattern like "*.ts" needs **/ prefix for recursive search").
- The 6 `.proto` files sit at depths 2-4, with none at the root, so a non-recursive `*.proto` finds 0. Distractors: `billing_pb2.py` and `order_events.proto.bak`. The instruction says what to list, not how (unforced).
- Oracle: PROTOS.txt equals the sorted list of 6 paths (a leading `./` is tolerated) and no proto files were created or deleted.
