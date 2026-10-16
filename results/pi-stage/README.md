# pi-stage (recovered 2026-10-16)

On 2026-10-16 the box was restored to an Oct 7 snapshot, and the original pi-stage/ was lost. Everything in this folder was rebuilt from the data on main.

- The fixtures `tasks/trig-omp-{cutover,dirread,finddir,findext,mdtable,tailread}` are **rewritten** to the same specs as the originals; they are not the originals. Each fixture's trigger was rechecked against its PR's parent and merge commits.
- The selftest passes 48/48 (16 tasks, each checked for fail, pass and echo). See `selftest.log`.
- `scoreboard-omp.*` was rebuilt from per-cell data on main. Row 36 is marked screened-null (data lost) until it is re-run.
- The token CSVs are built from the 522 Oh My Pi runs on main. Timeouts count as failures.
- Open guesses:
  - Row 26 maps to `trig-omp-fanout`; this is a guess.
  - Row 17 has no task yet. The change is always on, so it runs on multistep.
  - Row 24's change is on the PR's second parent.
- The OpenCode per-run data was lost in the restore.
