pair | measure | own base | variant | Fisher p (two-sided)
---|---|---|---|---
PERM-only (925226) | solved | 26/30 | 24/30 | 0.731
PERM-only (925226) | mktemp | 15/30 | 10/30 | 0.295
PERM-only (925226) | opencode | 0/30 | 0/30 | 1
PERM-only (925226) | leaked | 13/30 | 10/30 | 0.596
PERM-only (925226) | scratch_left | 0/30 | 0/30 | 1
PERM-only (925226) | rejections | 5/30 | 6/30 | 1
PROMPT-only (825226) | solved | 29/30 | 21/30 | 0.0122
PROMPT-only (825226) | mktemp | 8/30 | 0/30 | 0.00458
PROMPT-only (825226) | opencode | 0/30 | 9/30 | 0.00194
PROMPT-only (825226) | leaked | 7/30 | 0/30 | 0.0105
PROMPT-only (825226) | scratch_left | 0/30 | 1/30 | 1
PROMPT-only (825226) | rejections | 1/30 | 9/30 | 0.0122

Agreement with pooled (ANALYSIS-1022.txt): same conclusions. PERM-only is not different from its own base on any measure (all p>=0.29). PROMPT-only differs from its own base on mktemp, opencode/, leaked, rejections and solved (all p<=0.013); scratch_left is not significant. Base-vs-base check between the two rows' without sides (same build 33f7f593):
base-vs-base solved: 26/30 vs 29/30 p=0.353
base-vs-base mktemp: 15/30 vs 8/30 p=0.11
base-vs-base leaked: 13/30 vs 7/30 p=0.17
base-vs-base rejections: 5/30 vs 1/30 p=0.195
