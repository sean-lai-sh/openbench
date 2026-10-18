# Do fewer tool calls go with lower token cost?

Written 2026-10-17 at 8:50 PM ET from stored cells on main. No benchmark was run and no stored number was changed. Re-run with `python3 results/toolcalls-vs-tokens-1017/toolcalls_tokens.py` from the repo root (standard library only, about 25 s).

## Short answer
**Mostly yes, but tool calls are a proxy.** Token cost follows the number of **model round trips** (requests) times the **context each request carries**. More tool calls cost more only when they add round trips.

- **Within a run:** cells with more tool calls use more tokens.
  - Pooled Spearman ρ = +0.72 (n = 2,865); +0.80 on OpenCode and +0.52 on Oh My Pi.
  - All 44 per-PR rows that vary show a positive correlation (median ρ +0.78), and 43 of them have p < 0.05.
- **Across PRs:** the % change in tool calls tracks the % change in tokens with Spearman ρ = +0.64 over 43 A/B rows (Pearson on log ratios r = +0.86).
  - The % change in requests tracks tokens more closely: ρ = +0.88.
  - On OpenCode A/B the gap is clearer: tool calls ρ = +0.73, requests ρ = +0.94.
  - Oh My Pi has only 6 A/B rows and shows no relation (ρ = +0.14, p = 0.79).
- **Exceptions run both ways** (see "Counterexamples").
  - Some PRs changed tokens through **prompt size** while tool calls stayed flat: OMP row 16 as expected, 26821, and trivially 19058, 2367 and 5066.
  - Several PRs cut tool calls without saving tokens, because the calls they dropped were batched into the same request: 5140 and omp-33.

## Data (2,865 scored cells, 47 rows)
- **Step 3, Sonnet, OpenCode:** the 31 seeded-order PRs from the same canonical folders as #89.
- **Step 6, Opus, OpenCode:** `step6-opus-1017-{913,3052,13331,24974,25226,26821}`.
- **Step 4, Sonnet, Oh My Pi, B1:** `step4-omp-sonnet-1017`, rows omp-15, 16, 21, 28, 33 and 35. This is what is on main (#90); B2 is not.
- **A/A runs:**
  - `step5-opus-aa-1017-oc26821-aa` and `-omp36-aa`.
  - `aa-sonnet-1016/oc26821-aa` and `/omp36-aa`.

Scored cells are those whose `failure_class` is not infra, rate_limited, stalled or incompatible, the same rule as each run's `stats.py`.

## Definitions
**Tool calls** come from `thesis/ab/evidence.py`:
- **OpenCode:** `transcript_files` + `evidence_files` → `_metric_calls(paths, all)`. This is the same deduplicated call list behind the runner's read/edit counts, and it includes subagent calls.
- **Oh My Pi:** the `_pi_stream_events` / `_pi_messages` stream with `_pi_tool_calls`' id dedupe, but without its read/edit/write/bash name filter, so every tool counts.
- **Fallback for 623:** its OpenCode build stores old `"type":"tool-invocation"` parts, which evidence.py does not parse. Those 60 cells are counted by unique `toolCallId` with a small regex.
- **Check:** my read counts equal the runner's stored `read_calls` in 2,863 of 2,865 cells. The two differences are 623 cells, where the runner also sees 0.
- **Types:** read (read); edit (edit, multiedit, write, apply_patch); bash; search (grep, glob, list, ls, find, lsp); other (task 468, todowrite 303, skill 179, webfetch 120, plus 2 singletons).

**Tokens** match `boot.py`: `tokens_input_uncached + tokens_output + tokens_cache_read + tokens_cache_write`. Input is everything except output.
- **% change:** ratio of the side means with the same 10k percentile bootstrap and `random.Random(0)` as `boot.py`. The recomputed token % changes match the reported step 3, 4 and 6 numbers.
- **Step-2 Sonnet OpenCode A/A:** this table keeps 4 hang cells, so it reads +8.2%. The reported A/A band excluded those hangs.

**Per-request context** comes from each run's `proxy-ledger`, joined to cells by their exact `requests_*` totals. 5 cells did not match: 2334 ×3 and 13331 ×2.
- OpenCode's session-title request is tiny (252–1,900 context tokens). "Agent requests" are those with at least 3,000 context tokens.

## Output files
- `cells.csv`: every scored cell, with tool calls by type, turns, requests, total/input/output tokens, and first, mean and max agent-request context.
- `per_pr.csv`: one row per PR, model and run, with per-side tool-call medians and means, tool-call / token / request % changes with CIs, type means, and the within-PR Spearman correlation.
- `correlations.csv`, `decomposition.csv`, `output.txt`: full printouts.

## Per PR (tool calls vs tokens; 95% bootstrap CIs; full table in per_pr.csv)
| row | tool calls median w/o→w | tool calls % | tokens % | requests % |
|---|---|---|---|---|
| S3 3052 | 8→3 | −60.6 [−62.3, −58.8] | −64.8 [−66.7, −62.5] | −53.6 |
| O6 3052 | 6→3 | −49.1 [−52.5, −46.1] | −51.8 [−56.2, −48.0] | −42.1 |
| S3 13331 | 3→2 | −35.4 [−40.4, −29.2] | −27.9 [−32.1, −22.9] | −22.5 |
| O6 13331 | 3→2 | −31.6 [−37.2, −25.5] | −25.5 [−30.2, −20.5] | −20.6 |
| S3 26821 | 6.5→6 | −13.5 [−28.1, +4.5] | −26.5 [−34.2, −18.1] | −3.7 |
| O6 26821 | 13→7 | −20.7 [−36.8, −0.3] | −26.9 [−34.3, −18.8] | −6.2 |
| S3 913 | 6→6 | −0.6 [−1.7, 0.0] | −2.7 [−6.2, −0.6] | −1.7 |
| O6 913 | 5→6 | +16.3 [+13.3, +19.2] | +23.4 [+17.3, +29.5] | +18.6 |
| OMP 16 | 3→3 | −6.0 [−29.1, +24.2] | +42.5 [+13.4, +76.4] | −4.2 |
| S3 5140 | 8→4 | −24.5 [−35.8, −11.1] | −2.4 [−13.9, +10.6] | −3.4 |
| OMP 33 | 8→8 | −20.7 [−33.0, −8.0] | −4.0 [−9.6, +2.4] | −4.4 |
| OMP 21 | 5→7.5 | +21.6 [+8.5, +37.0] | +4.4 [−2.2, +11.2] | +2.9 |
| O6 25226 | 7→5 | −10.3 [−22.3, +3.2] | +13.8 [−1.1, +30.4] | +12.8 |
| A/A Opus OC 26821 | 14.5→13 | −13.7 [−28.3, +4.5] | −3.2 [−10.2, +4.7] | −1.5 |
| A/A Opus OMP 36 | 7→7 | +2.5 [−4.2, +9.4] | +1.1 [−6.1, +8.9] | +1.1 |
| A/A Sonnet OC 26821 | 7→7 | −5.7 [−24.7, +19.7] | +8.2 [−1.3, +20.4] (incl. hangs) | +8.1 |
| A/A Sonnet OMP 36 | 5→5 | +1.9 [−4.3, +9.7] | +4.0 [−3.4, +13.8] | +4.1 |

Row prefixes: S3 = step 3 Sonnet OpenCode, O6 = step 6 Opus OpenCode, OMP = step 4 Sonnet Oh My Pi.

Pattern counts over 47 rows:
- Both CIs include 0: 28.
- Both exclude 0, same direction: 6 (3052 ×2, 13331 ×2, Opus 913, Opus 26821).
- Tokens move, tool calls flat: 7.
- Tool calls move, tokens flat: 6.
- Opposite directions: 0.

Tool-call counts are noisy. The Opus OpenCode A/A alone swings −13.7% [−28.3%, +4.5%], so a tool-call change smaller than about ±25% on OpenCode is not distinguishable from noise.

## Counterexamples
**Tokens move, tool calls flat:**
- **OMP row 16** (+42.5% tokens, −6.0% tool calls): this is prompt size, as expected. The first agent request grows from 19,099 to 29,517 context tokens, about +10.4K on every request. Over about 4.6 requests that is roughly +47K, against an observed input change of +42.5K. Requests fall 4.2%, so 112% of the log change comes from tokens per request.
- **Sonnet 26821** (−26.5% tokens, tool calls −13.5% and not significant): also mainly prompt size. The first agent request shrinks from 15,957 to 11,318 (−4.6K), on both Sonnet and Opus. Over about 8.7 requests that is roughly −40K, against an observed input change of −39K. Per-request size explains 88% of the log change (80% on Opus), and requests fall only 3.7%.
  - Opus 26821 also cuts tool calls (median 13→7, −20.7%), mostly edits and reads.
- **19058, 2367 and 5066** (Sonnet): deterministic paths with identical tool calls and requests on both sides. Tokens change by 0.1–0.2%, which is just the PR's prompt text.
- **913 on Sonnet** (−2.7% tokens) and **OMP row 28** (+2.8%): small token changes with flat tool calls, inside the A/A bands.

**Tool calls move, tokens flat:**
- **5140** (Sonnet): tool calls −24.5% (median 8→4), almost all from reads (2.67→0.87 per cell). Requests fall only 3.4% and tokens 2.4% (not significant). The dropped reads had been issued in parallel inside requests the agent made anyway.
- **OMP row 33:** tool calls −20.7% (reads 4.6→3.3, edits 1.0→0.6), requests −4.4%, tokens −4.0% (not significant). Same pattern.
- **OMP row 21:** tool calls +21.6% (more search and read), requests +2.9%, tokens +4.4% (not significant).
- **4838, 21070 and 24974** (Sonnet): tool-call changes of 6–17% with token CIs that include 0. These are borderline.
- **Opus 25226** (not significant either way): tool calls −10%, tokens +14%, requests +13%. The with side made more round trips with fewer reads, so this row runs against "fewer tool calls, fewer tokens".

## Where the token changes come from (side means; ln T = ln R + ln(T/R))
| row | tokens w/o→w | requests w/o→w | tokens/request | share: requests / per-request | first agent request context | mean agent request context |
|---|---|---|---|---|---|---|
| S3 3052 | 132,946→46,828 (−64.8%) | 8.55→3.97 | 15,546→11,805 | 74% / 26% | 15,295→15,292 | 17,148→15,541 |
| O6 3052 | 95,050→45,773 (−51.8%) | 6.73→3.90 | 14,116→11,737 | 75% / 25% | 15,295→15,293 | 16,292→15,541 |
| S3 13331 | 70,252→50,653 (−27.9%) | 5.33→4.13 | 13,172→12,255 | 78% / 22% | 15,640→15,638 | 15,964→15,785 |
| O6 13331 | 70,227→52,327 (−25.5%) | 5.33→4.23 | 13,168→12,361 | 79% / 21% | 15,638→15,638 | 16,023→15,801 |
| S3 26821 | 148,977→109,483 (−26.5%) | 8.97→8.63 | 16,615→12,681 | 12% / 88% | 15,957→11,318 | 16,142→12,315 |
| O6 26821 | 160,303→117,116 (−26.9%) | 9.10→8.53 | 17,616→13,725 | 20% / 80% | 15,957→11,319 | 17,052→13,252 |
| S3 913 | 76,687→74,613 (−2.7%) | 6.00→5.90 | 12,781→12,654 | 63% / 37% | 14,493→14,492 | 15,140→15,045 |
| O6 913 | 63,966→78,942 (+23.4%) | 5.20→6.17 | 12,301→12,801 | 81% / 19% | 14,492→14,493 | 15,017→15,082 |
| OMP 16 | 99,664→142,059 (+42.5%) | 4.73→4.53 | 21,056→31,337 | −12% / 112% | 19,099→29,517 | 20,536→30,885 |

Input tokens account for nearly all of every change; output moves by at most 2.5K per cell. Tokens per request here includes the small OpenCode title request.

**3052 and 13331: the number of calls.**
- In 3052, the parent's image read fails and the agent falls back to bash: 5.1 bash calls per cell on Sonnet and 2.6 on Opus, versus 0 with the fix. About three-quarters of the token saving comes from fewer round trips. The rest is less context growth per request, from the failed-read output carried along: growth over the first request is 1,852 → 249 on Sonnet.
- In 13331, the parent decodes the image by hand with bash (1.9 → 0.13 bash per cell). Again about 78% of the change is fewer requests.
- In both PRs the base prompt is identical on the two sides.

**913 on Opus: the number of calls.** The with side adds a bash retry with bare python after `venv/` is hidden (bash 1.10 → 1.93 per cell), giving 18.6% more requests. 81% of the token increase comes from the extra round trips.

**26821 and OMP row 16: per-call context.** Per-request size explains 80–112% of the change, driven by system-prompt or tool-definition size (−4.6K and +10.4K tokens on the first agent request), not by how many tools the agent calls.

## Caveats
1. **Tool calls and requests are different units.** Parallel tool calls share one request, and OpenCode adds a title request. The cell-level correlations are partly mechanical: every extra round trip re-sends the context.
2. **Oh My Pi has only 6 A/B rows,** so its across-PR correlation is not informative. Within runs, OMP tool calls still correlate with tokens (ρ +0.52; +0.64 on centred within-row ranks).
3. **Not every cell joined to its ledger.** 5 cells have no matching proxy ledger and are left out of the first/mean agent-request context only. 60 Opus 913 cells have no stored `turns`.
4. **This is correlational.** The decomposition is an accounting identity, not a causal model. The mechanisms named for 3052, 13331 and 913 come from the tool-type breakdowns in `per_pr.csv` and the earlier room findings.
