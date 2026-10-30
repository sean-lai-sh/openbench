# Pi vs OpenCode 180-cell batch: notes (2026-10-29)

## 1. Checker-timeout cells: env_failure, excluded from scoring

40 cells (20 per side) ended with `failure_class: timeout` after the checker
ran to its 120 s cap (`t_checker_s` >= 119 s). These are checker timeouts,
not agent failures. They are marked here as
`env_failure` with `env_cause=checker_timeout` and are **excluded from scoring**
until they are rerun on the #191 checker (prebuilt venvs, 600 s budget).
The raw cell JSON is left unchanged; this note is the classification of record.

| task | Pi cells | Pi checker_timeout | Pi solved/scored | OC cells | OC checker_timeout | OC solved/scored |
|---|---|---|---|---|---|---|
| dna-insert | 10 | 0 | 2/10 | 10 | 0 | 2/10 |
| filter-js-from-html | 10 | 0 | 2/10 | 10 | 0 | 5/10 |
| model-extraction-relu-logits | 10 | 1 | 8/9 | 10 | 1 | 7/9 |
| polyglot-rust-c | 10 | 0 | 0/10 | 10 | 0 | 0/10 |
| regex-chess | 10 | 0 | 10/10 | 10 | 0 | 3/10 |
| sam-cell-seg | 10 | 0 | 0/10 | 10 | 0 | 0/10 |
| torch-pipeline-parallelism | 10 | 10 | 0/0 | 10 | 10 | 0/0 |
| torch-tensor-parallelism | 10 | 9 | 1/1 | 10 | 9 | 1/1 |
| video-processing | 10 | 0 | 2/10 | 10 | 0 | 4/10 |
| **all** | 90 | 20 | 25/70 (35.7%) | 90 | 20 | 22/70 (31.4%) |

Provisional solve rates are computed over scored cells only (cells minus checker timeouts):
**Pi 25/70 = 35.7%, OpenCode 22/70 = 31.4%** (over all 90: 27.8% vs 24.4%).

Clustering: the timeouts are by task, not by side. Both sides have exactly the same
count on every task: torch-pipeline-parallelism 10/10, torch-tensor-parallelism 9/10,
model-extraction-relu-logits 1/10. Those are the torch-heavy checkers that #191 moves to
prebuilt venvs. torch-pipeline-parallelism has no scored cells on either side, and
torch-tensor-parallelism has only one per side, so neither task can be compared until the reruns.

Borderline: `001-opencode-model-extraction-relu-logits-r7` had `t_checker_s` = 119.4 s
but the checker exited 1 (`wrong_answer`), so it finished and stays scored.

Checker-timeout cells (40):
- 000-pi-torch-tensor-parallelism-r6
- 002-pi-torch-tensor-parallelism-r8
- 003-pi-torch-pipeline-parallelism-r5
- 010-opencode-torch-pipeline-parallelism-r6
- 038-opencode-torch-pipeline-parallelism-r8
- 048-pi-torch-tensor-parallelism-r3
- 049-opencode-torch-tensor-parallelism-r1
- 053-pi-torch-tensor-parallelism-r5
- 055-opencode-torch-pipeline-parallelism-r10
- 061-pi-torch-tensor-parallelism-r7
- 062-opencode-torch-tensor-parallelism-r10
- 064-opencode-torch-pipeline-parallelism-r2
- 065-pi-torch-pipeline-parallelism-r1
- 066-opencode-torch-pipeline-parallelism-r4
- 070-opencode-torch-pipeline-parallelism-r9
- 073-pi-model-extraction-relu-logits-r8
- 082-pi-torch-tensor-parallelism-r1
- 093-opencode-torch-tensor-parallelism-r4
- 096-opencode-torch-tensor-parallelism-r3
- 103-pi-torch-pipeline-parallelism-r7
- 109-pi-torch-pipeline-parallelism-r8
- 118-pi-torch-pipeline-parallelism-r4
- 121-opencode-torch-pipeline-parallelism-r5
- 123-pi-torch-tensor-parallelism-r2
- 126-pi-torch-pipeline-parallelism-r3
- 133-opencode-model-extraction-relu-logits-r8
- 137-pi-torch-pipeline-parallelism-r2
- 138-opencode-torch-pipeline-parallelism-r3
- 139-opencode-torch-tensor-parallelism-r9
- 140-pi-torch-pipeline-parallelism-r10
- 143-opencode-torch-tensor-parallelism-r2
- 144-pi-torch-tensor-parallelism-r10
- 153-pi-torch-pipeline-parallelism-r6
- 154-pi-torch-pipeline-parallelism-r9
- 161-opencode-torch-tensor-parallelism-r6
- 164-opencode-torch-pipeline-parallelism-r7
- 170-opencode-torch-tensor-parallelism-r8
- 175-opencode-torch-tensor-parallelism-r7
- 176-pi-torch-tensor-parallelism-r9
- 179-opencode-torch-pipeline-parallelism-r1

## 2. Why OpenCode transcript filenames say claude-opus-5-5

It's only a filename quirk. Every OpenCode cell requested and was served Sonnet.

- `data/opencode-harness-smoke/cell.py:33` sets `ADAPTER_MODEL = "claude-opus-5-5"`. This is the
  adapter key that selects the proxy route. The launched model is `MODEL_REF = "anthropic/claude-sonnet-5-5"`
  (line 34), and the proxy's upstream model is `--vertex-model claude-sonnet-5-5`. Line 239 passes
  `ADAPTER_MODEL` as the `model` argument to `run_cell(...)`.
- `obench/run.py:260` builds `run_id = f"{group}:{task}:{model}:trial{trial}"` from that argument, and
  `obench/run.py:1661-1670` (`transcript_path`) sanitizes the run_id into the filename, giving
  `opencode_<task>_claude-opus-5-5_trial1.txt`. The directory and results JSON name come from the
  Sonnet vertex model.
- Each OpenCode row also records `adapter_model: claude-opus-5-5` beside
  `harness_model: anthropic/claude-sonnet-5-5`, `requested_model`/`upstream_model: claude-sonnet-5-5`,
  `off_protocol: false`, and `require_model_match: true`.
- Ledger evidence, from all 180 cells' `proxy-ledger/*.jsonl` request records:
  OpenCode had 761 requests and Pi had 370, all with `requested_model = upstream_model = claude-sonnet-5-5`.
  There were 0 requests with any other model, and no row was off_protocol or mixed-model.
