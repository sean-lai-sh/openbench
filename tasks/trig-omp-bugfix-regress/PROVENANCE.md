# Provenance

- Source: authored locally for the thesis Oh My Pi A/B stage.
- Trigger for OMP row 38 (bug fix -> "SHOULD keep the reproduction as a regression test"). `pricing/money.py::round_money` uses `round(x, 2)`, which is binary-float half-even (2.675 -> 2.67). Existing tests cover other functions only, so whether a regression test is added is the outcome metric.
- Oracle: checker's own tests for round_money (half-up on decimal string value) and the untouched helpers.
