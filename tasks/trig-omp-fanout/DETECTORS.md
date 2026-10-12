# Detectors: trig-omp-fanout (row 28)

- **Subagent spawns (side-specific signal):** count tool calls named `task` in the parent session; for each, count `tasks[]` items (batch) = subagents spawned. Report: runs with ≥1 task call, mean subagents/run.
- **Subagent cost:** sum tokens of all provider requests whose session/agent id is a child of the run's root session (proxy meter tags or OMP session files under the run HOME, one file per subagent). Report root-only and root+children totals separately; both feed the cost metric.
- **Wall time:** run start -> final answer.
- **Precondition (exercised):** ≥4 of the 5 app/*.py files modified in the final workspace (true on every pass). Without a task call, the row is "exercised but no fan-out".
- Parent build has the weaker delegation wording, so fan-out can also appear there; the comparison is the rate.
