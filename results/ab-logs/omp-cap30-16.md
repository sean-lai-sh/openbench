# Oh My Pi row 16 (tools block in system prompt) at 30/side
a92d867, trig-omp-multistep, interleave seed 20261014, jobs 8, timeout 360. Ran 17:00-17:17 PT 2026-10-12. Opus 5.5 via vertex-anthropic proxy.

- First-request prompt: 19,098.5 -> 29,516.8 tokens (+10,418, 95% CI +/-0.7; sd 1.5 / 1.1). +54.6%.
- Total tokens/run (in+out+cache r/w): 164.7K -> 254.9K (+90.1K +/-15.0K, +54.7%).
- Output tokens 2,024 -> 1,999 (-25 +/-180, n.s.); requests/run 7.9 -> 8.1 (n.s.).
- Pass 30/30 vs 29/30. The one merge fail (trial 18) is failure_class=timeout: harness hung ~350 s after a bash tool call with no tool result, 3 requests, no provider error. The 300 s no-progress watchdog did not fire.
- Tools/run: bash 6.1 -> 6.3, edit 1.0 -> 0.97, write 0.4 -> 0.53, read 0.03 -> 0.03.
- Ledger cost: $6.04 parent, $14.00 merge, $20.04 total.
- Cause (exact count_tokens on the captured request #1): the merge's extra tokens are all the new <tools> block (+10,494) minus the old one-line tool list (-76), plus 1 token of environment noise. Largest parts: task 4,942, edit 1,169, todo_write 724, puppeteer 714, bash 572. Matches the diff (system-prompt.md <tools>{{#each toolDescriptions}}, system-prompt.ts toolDescriptions). Tool schemas (tools[]) are byte-identical on both sides.
