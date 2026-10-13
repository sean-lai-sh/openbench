# Detectors: trig-omp-callsites (row 31; reusable for rows 18, 29, 27, 34)

Per run, from tool calls:
- **Shell search/list (rows 31, 29, 34):** bash calls whose command matches `(^|[|;&]\s*)(grep|rg|ag|ack|git grep|find|fd|ls|head|tail|cat)\b`. Count each; report grep/rg separately from ls/find and head/tail. Row 31's merge drops the NEVER rules, so expect more; row 29's merge adds MUST rules, so expect fewer.
- **Search tool use:** calls to `grep`/`search` tool (name depends on build). Count, and sum tool-result tokens.
- **Row 18 (grep limit 20, round-robin):** search results that report a match-limit/truncation notice; number of follow-up searches for the same pattern; missed call sites = checker fail with remaining references.
- **Row 27 (`paths` optional):** search calls with no `paths` arg or empty list; parent build returns an error result for these (count error results).
- Exercised = ≥1 content search (tool or shell) for `legacy_fetch`. Outcome secondary: pass rate (missed sites), tool calls, tokens.
