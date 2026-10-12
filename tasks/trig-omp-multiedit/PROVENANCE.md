# Provenance

- Source: authored locally for the thesis Oh My Pi A/B stage.
- Trigger for OMP row 20 (hashline edit-tool prompt rewrite; hashline is the default edit mode at that commit). One ~200-line file, five edit sites in different functions; handlers repeat identical lines (`return None`, `}`, `result = {`) so anchoring on non-unique lines and range-end/closer mistakes are possible.
- Oracle requires ValueError for `""` and whitespace-only `"   "` on all five handlers, with no store mutation; behaviour for valid ids and missing users is unchanged.
- Oracle: checker's own tests + `py_compile`.
