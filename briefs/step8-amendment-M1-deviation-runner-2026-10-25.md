# Step-8 amendment M1, deviation note D1: VM runner (2026-10-25)

Applies to: briefs/step8-amendment-machine-move-2026-10-25.md (M1, sha 80e5d2b4…b6b6, merged in #137 as 6dee350b).

## What changed
Step-8 cells on the thesis-h1-cpu VM run on runner commit 980e71b6 (PR #113) instead of the step-8 runner commit. 980e71b6 is the step-8 runner plus opt-in VM-credential and cell-meta flags. It makes no changes to scoring or token accounting.

## Why
The step-8 runner commit cannot authenticate to Vertex on the VM (see NOTES.txt in PR #139).

## Validation
The M1 stock OpenCode A/A check ran on 980e71b6 on thesis-h1-cpu: parent of 26821, trig-todo-task, Sonnet, 30 per side, seed 1016, interleave-seeded. Token delta +1.3% [−5.5, +8.3] (10k bootstrap, hangs excluded) overlaps the Sonnet OpenCode band +0.1% [−6.5, +6.8]. Passes 28/30 and 26/30, all failures hangs. Spend $14.15. Data: PR #139 (cbae57f5).

## Decision
Under M1, VM step-8 results pool with the shared-computer results.

## Conditions
1. Every step-8 VM cell runs on 980e71b6; a cell on any other runner is not pooled without a new A/A check.
2. Every cell records the runner sha next to the machine column.
