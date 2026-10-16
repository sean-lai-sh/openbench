# Detectors: trig-omp-finddir (row 25)

- **Directory lookup via `find` (primary):** `find` tool calls whose pattern names the directory (`**/golden`, `golden`, `**/golden/`). On the merge build the result lists `.../golden/` (directories now returned with a `/` suffix); on the parent only files come back. Per run, record: first find pattern, whether its result contained a path ending in `golden/`, and the number of find calls before the first write.
- **Fallbacks:** bash `find -type d`, `ls -R`, or `grep`/`search` used to locate the dir after a find call returned no directory. Count per run.
- **Steps to locate:** tool calls before the first write to the golden dir.
- Exercised = ≥1 `find` tool call. If the model uses only bash/search, the row is "not exercised" for that run.
