# Provenance

- Source: re-authored 2026-10-16 for the thesis Oh My Pi A/B stage (the original was lost in the box restore).
- Trigger for OMP row 24 (PR #1100, 2d96feb6; the change is on the PR's second parent, `git show 2d96feb6^2`): read.md and search.md now say "The pipe character after the hash is a separator, not part of the file content". The inventory's parent cb968ed5 gives an empty diff against the merge for these files; the diff was confirmed on the PR head.
- The line to edit is a Markdown table row, so it is full of `|` (plus one escaped `\|`). That is exactly where an anchor like `41th|` could be misread as content. The task only asks for a doc update (unforced).
- Oracle: only the search row changes, its Limit cell becomes `120/min`, and the pipe count, the other cells and every other line are unchanged.
