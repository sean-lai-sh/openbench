# Provenance

- Source: authored locally for the thesis Oh My Pi A/B stage.
- Trigger for OMP row 21 (adds "no renaming unused parameters to `_var`... If something is unused, delete it completely" and "prefer editing over creating"). `make lint` runs a small stdlib linter (`tools/lint.py`, mirrors ruff ARG001: unused function arguments; names starting with `_` and lines with `# noqa` are exempt, like ruff). One violation: `on_save(doc, ctx)` never uses `ctx`; it has two internal callers.
- Both fixes (delete the parameter and update callers, or rename to `_ctx`/noqa) pass. The style is the outcome metric, not the verdict.
- Oracle: checker runs its OWN copy of the linter (checker_data/lint.py) so editing tools/lint.py can't pass, plus the checker's tests.
- Environment: python3, make (both on the box).
