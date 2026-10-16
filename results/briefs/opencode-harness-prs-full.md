# OpenCode harness PRs — reviewed inventory v2 (2026-10-16)

Repo anomalyco/opencode (sst/opencode redirects), dev @ bc5ebf00a. 1,963 merged PRs touch widened harness paths (adds lsp/, file/, format/, shell/, skill/, config/, patch/ …; catches 19058/2334/6524). Each diff scanned by script (git show -U0); ~90 sampled by hand to tune rules. Earlier 34 keep their manual review. Rules: exclude non-Anthropic-only provider/prompt code, no model-facing change, UI/auth, fully reverted pairs (revert-of-revert kept as one).

Included 447: {'conditional': 209, 'always-on': 185, 'needs-new-task': 53}
Categories: {'tool': 103, 'prompt': 33, 'subagent/agent': 62, 'loop': 101, 'provider-format': 44, 'permission': 36, 'lsp/diagnostics': 3, 'context': 48, 'edit-logic': 1, 'session-other': 15, 'mcp': 1}
Excluded: {'non-anthropic': 191, 'no-model-visible': 1226, 'provider-auth': 24, 'ui-only': 57, 'reverted': 18}

Estimated spot-check precision of included rows is ~80%; reviewed=scripted-diff rows still need a human look before launch.

|PR|merged|category|exercisable|trigger / new-task spec|34|title|
|-|-|-|-|-|-|-|
|294|2025-06-22|tool|conditional|trig-dup-edit|no|ignore: fix typos and formatting|
|300|2025-06-22|tool|always-on|trig-bash-limits|no|combine stdout and stderr in bash tool output|
|623|2025-07-02|prompt|always-on|EXISTING `make-it-run`, unchanged. The edited sentence is in the Claude system prompt sent|yes|Update prompt reference from CLAUDE.md to AGENTS.md|
|624|2025-07-02|prompt|always-on|any existing task (make-it-run)|no|feat: configurable instructions|
|579|2025-07-02|tool|always-on|trig-read-lines|no|chore: rename OpenCode to opencode|
|775|2025-07-08|tool|conditional|trig-todo-task|no|fix: support cancelled task state|
|795|2025-07-09|tool|conditional|trig-lsp-ts|no|LSP: fix SimpleRoots to actually search in the root directory|
|913|2025-07-12|tool|conditional|NEW (proposed) `trig-list-noise`: 3-file Python project (`src/app.py`, `tests/test_app.py`|yes|feat: add more ignore patterns to the ls tool|
|950|2025-07-13|subagent/agent|conditional|trig-subagent-resume|no|Part data model|
|984|2025-07-14|tool|conditional|EXISTING `make-ci-green`, unchanged (several files need edits, so edit is called repeatedl|yes|Standardize parameter description references in Edit and MultiEdit tools|
|1031|2025-07-15|prompt|always-on|any existing task (make-it-run)|no|move spoof prompt to support anthropic with custom modes|
|1109|2025-07-17|prompt|always-on|any existing task (make-it-run)|no|Update to a customized beast mode v3 for opencode.|
|1128|2025-07-18|subagent/agent|conditional|trig-subagent-resume|no|wip: optional IDs in api|
|1268|2025-07-23|loop|always-on|any existing task (make-it-run)|no|basic undo feature|
|1248|2025-07-23|subagent/agent|conditional|NEW (proposed) `trig-plan-subagent`: copy of `misleading-error` workspace and checker. The|yes|feat: pass mode into task tool|
|1287|2025-07-24|tool|always-on|make-ci-green|no|fix: edit tool|
|1284|2025-07-24|provider-format|always-on|any existing task (Anthropic path)|no|Check if modelID includes "claude" for antropic/claude prompt caching|
|1305|2025-07-25|provider-format|always-on|any existing task (Anthropic path)|no|fix: apply content-level caching for non-anthropic providers|
|1443|2025-07-30|loop|always-on|trig-read-lines|no|use treesitter to parse bash commands and catch commands that go outside of cwd|
|1525|2025-08-01|provider-format|always-on|any existing task (Anthropic path)|no|feat(models): enable Kimi k2 ⇄ Claude trajectory handoff|
|1529|2025-08-02|provider-format|always-on|any existing task (Anthropic path)|no|ignore: fix dev branch|
|1567|2025-08-03|prompt|always-on|any existing task (make-it-run)|no|tweak: filter out duplicate instructions|
|1627|2025-08-05|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|permissions disallow support|
|1642|2025-08-06|subagent/agent|conditional|trig-subagent-resume|no|fix: handle undefined agent in task tool|
|1689|2025-08-07|subagent/agent|conditional|trig-subagent-resume|no|Merge agent and mode into one|
|1761|2025-08-11|prompt|always-on|any existing task (make-it-run)|no|fix: only load the first local and global rule file|
|1762|2025-08-11|prompt|always-on|any existing task (make-it-run)|no|fix: instructions should be able to handle absolute paths|
|1791|2025-08-11|tool|conditional|make-it-run; verify which tool|no|Add support for biome.jsonc config file|
|1887|2025-08-12|subagent/agent|conditional|trig-subagent-resume|no|fix: task tool prompt|
|1862|2025-08-12|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|Add agent-level permissions with whitelist/blacklist support|
|1897|2025-08-13|subagent/agent|conditional|trig-subagent-resume|no|fix: grammatical error in agent launch example (by Opencode)|
|1879|2025-08-13|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|Merge default agent permissions with global config|
|1949|2025-08-15|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|Feat: Render tool metadata after permission rejection.|
|2008|2025-08-16|subagent/agent|conditional|make-it-run; verify which tool|no|feat: top level tool config|
|1991|2025-08-16|prompt|conditional|trig-plan-subagent|no|tweak: plan prompt, more explicit about not modifying files|
|2053|2025-08-18|subagent/agent|conditional|make-it-run; verify which tool|no|fix: ensure name isn't added as field in options: {...}|
|2150|2025-08-21|subagent/agent|always-on|make-ci-green|no|tweak: adjust plan agent to ask when running bash, give it edit tooli…|
|2111|2025-08-21|prompt|conditional|trig-plan-subagent|no|tweak: adjust plan -> build transition prompt|
|2260|2025-08-26|tool|always-on|trig-bash-limits|no|fix: bash tool description|
|2334|2025-08-30|lsp/diagnostics|conditional|NEW (proposed) `trig-lsp-ts`: `package.json`, `tsconfig.json`, `src/index.ts` with one typ|yes|add support for lsp workspace/didChangeConfiguration|
|2367|2025-09-02|tool|conditional|NEW (proposed) `trig-list-noise` (same as #913) plus a `.ignore` file listing `generated/`|yes|tweak: update ls tool to use rg|
|2424|2025-09-04|tool|conditional|trig-webfetch-image|no|fix: webfetch prompt mistake|
|2051|2025-09-05|loop|always-on|make-ci-green|no|tweak(edit): separate edit tool error message with clearer guidance to avoid llm doom editing loop|
|2056|2025-09-07|provider-format|always-on|any existing task (Anthropic path)|no|fix: max output tokens when setting budget thinking tokens|
|2505|2025-09-08|subagent/agent|always-on|make-ci-green|no|remove edit tool from plan agent|
|2420|2025-09-08|tool|conditional|make-it-run; verify which tool|no|feat: add dynamic tool registration for plugins and external services|
|2525|2025-09-09|prompt|always-on|any existing task (make-it-run)|no|tweak: wrap build-switch w/ system-reminder|
|2533|2025-09-10|loop|always-on|any existing task (make-it-run)|no|fix: handle @dir in command|
|2569|2025-09-13|subagent/agent|conditional|make-it-run; verify which tool|no|respect subagent in command, add `subtask` flag|
|2583|2025-09-13|loop|always-on|any existing task (make-it-run)|no|tweak: keep aborted msgs in context|
|2577|2025-09-13|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|Session management and prompt handling improvements|
|2602|2025-09-14|loop|always-on|any existing task (make-it-run)|no|fix: reasoning metadata persistence|
|2592|2025-09-14|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|tweak: make bash permissions key off of command pattern|
|2466|2025-09-14|subagent/agent|conditional|trig-subagent-resume|no|fix: fix wrong tool references `LS` and `Agent`|
|2659|2025-09-17|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix: add synthetic user prompt after session compaction|
|2651|2025-09-17|loop|always-on|any existing task (make-it-run)|no|fix: only keep aborted messages if they have sufficient parts|
|2668|2025-09-18|tool|conditional|make-it-run; verify which tool|no|support custom tools|
|2976|2025-10-04|loop|always-on|any existing task (make-it-run)|no|fix: max output tokens when using large thinking budget|
|2986|2025-10-05|tool|always-on|trig-bash-limits|no|fix: add timeout message if command times out|
|3006|2025-10-07|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|fix: mcp error|
|3052|2025-10-09|loop|always-on|NEW (proposed) `trig-image-read`: workspace has `spec.png` (rendered text "PORT = 8417") a|yes|feat: allow read tool to handle images|
|3115|2025-10-12|tool|conditional|NEW (proposed) `trig-list`: copy of EXISTING `add-feature`, instruction prefixed with "Sta|yes|fix: adjust list tool prompt to handle cwd better|
|3192|2025-10-15|tool|always-on|trig-bash-limits|no|Revert "fix: spawns hanging  (#3192)"|
|3079|2025-10-15|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|feat: make compact feature use streaming API|
|3192|2025-10-15|tool|always-on|trig-bash-limits|no|fix: spawns hanging|
|3185|2025-10-15|subagent/agent|conditional|trig-subagent-resume|no|tweak: consolidate session lock logic|
|3210|2025-10-16|tool|conditional|trig-lsp-ts|no|feat: deno lsp|
|3225|2025-10-16|tool|always-on|trig-bash-limits|no|fix: bash hangs & orphans|
|3251|2025-10-18|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|make compact interruptable|
|2947|2025-10-20|loop|always-on|add-feature|no|feat: Add ACP (Agent Client Protocol) support|
|3302|2025-10-20|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix: bash tool permission merges|
|3369|2025-10-22|context|conditional|EXISTING `make-it-run` plus proxy fault injection: the Vertex proxy returns HTTP 529 (or 4|yes|feat: retry parts|
|3390|2025-10-23|tool|always-on|trig-bash-limits|no|add flag wildcard parsing support for bash tool|
|3381|2025-10-23|loop|always-on|any existing task (make-it-run)|no|fix: allow `tool.execute.after` hook to modify MCP tool output|
|3424|2025-10-24|subagent/agent|conditional|trig-plan-subagent|no|make plan agent whitelist more conservative|
|3418|2025-10-24|edit-logic|conditional|NEW (proposed) `trig-dup-edit`: `limits.py` with two functions that each contain the ident|yes|adjust edit tool multiple matches error wording|
|3402|2025-10-24|tool|conditional|trig-lsp-ts|no|feat: support lua lsp|
|3449|2025-10-25|tool|conditional|trig-lsp-ts|no|fix: $ invocation not .quiet()|
|3433|2025-10-25|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|feat: add noReply parameter|
|3507|2025-10-28|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|add --title flag to opencode run|
|2116|2025-10-28|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|tweak: add experimental chatMaxRetries to config|
|3481|2025-10-30|loop|conditional|trig-lsp-ts|no|fix: Opencode hangs after exit|
|3546|2025-10-30|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|add optional headers field to model config|
|3677|2025-11-01|loop|always-on|any existing task (make-it-run)|no|make /init a default slash command on server side|
|3757|2025-11-02|subagent/agent|conditional|trig-subagent-resume|no|fix: typos|
|1545|2025-11-11|tool|conditional|trig-lsp-ts|no|feat: add SourceKit LSP support|
|4221|2025-11-11|subagent/agent|conditional|trig-subagent-resume|no|fix: resolve @file references in slash commands with subagents|
|4226|2025-11-11|subagent/agent|conditional|make-it-run; verify which tool|no|feat: agent color cfg|
|3611|2025-11-12|tool|conditional|trig-lsp-ts|no|fix: clangd hanging fixed|
|2983|2025-11-15|tool|needs-new-task|NEW trig-batch: task needing many independent reads, batch tool enabled|no|experimental batch tool|
|4387|2025-11-16|tool|needs-new-task|NEW trig-batch: task needing many independent reads, batch tool enabled|no|fix(batch): restore per-tool UI feedback + UX improvements|
|4396|2025-11-17|tool|needs-new-task|NEW trig-batch: task needing many independent reads, batch tool enabled|no|fix(batch): simple UX feedback|
|4433|2025-11-18|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix: permission checks for external_directory and doom_loop|
|4505|2025-11-19|loop|always-on|any existing task (make-it-run)|no|fix: resolve issue 4475|
|4204|2025-11-19|subagent/agent|conditional|NEW (proposed) `trig-subagent-resume`: copy of EXISTING `misleading-error`, instruction pr|yes|allow task tool to have resume capabilities|
|4554|2025-11-20|session-other|conditional|make-it-run (path fires only on specific events; see diff)|no|feat: add field to allow user only messages|
|4540|2025-11-20|session-other|always-on|any existing task (make-it-run)|no|Revert "Image tag fix for real this time (#4540)"|
|4540|2025-11-20|session-other|always-on|any existing task (make-it-run)|no|Image tag fix for real this time|
|4497|2025-11-20|tool|always-on|trig-bash-limits|no|Make the MAX_OUTPUT_LENGTH in bash.ts overridable by OPENCODE_EXPERIMENTAL_BASH_MAX_OUTPUT_LENGTH|
|4617|2025-11-21|loop|always-on|any existing task (make-it-run)|no|enterprise|
|4556|2025-11-21|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix: preserve agent context during compaction|
|4562|2025-11-22|loop|always-on|any existing task (make-it-run)|no|proper fix for image attachments|
|4654|2025-11-24|loop|always-on|any existing task (make-it-run)|no|config: add setCacheKey in provider options|
|4805|2025-11-26|tool|conditional|make-it-run; verify which tool|no|enable parcel file watcher, expand parcel ignore patterns, replace fs watcher for git branches with parcel|
|4811|2025-11-28|session-other|always-on|any existing task (make-it-run)|no|fix: filter empty messages in toModelMessage|
|4838|2025-11-30|context|conditional|EXISTING `taskflow` with a runner config override `limit.context = 72000` on both sides, s|yes|tweak: compaction prompt|
|5033|2025-12-03|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|core: refactor provider and model system|
|4913|2025-12-03|subagent/agent|conditional|trig-subagent-resume|no|feat: experimental.primary_tools, allow user to set the tools that should only be available to primary agents|
|5066|2025-12-04|context|conditional|NEW (proposed) `trig-bash-limits`: copy of EXISTING `fix-failing-test`, instruction prefix|yes|tweak: bash tool messages regarding timeouts and truncation more clear for agent|
|5131|2025-12-05|tool|always-on|Same `trig-bash-limits` as #5066.|yes|tweak: bash tool improve output metadata for agent consumption, fix small timeout issue|
|4062|2025-12-05|prompt|always-on|any existing task (make-it-run)|no|feat: add max steps for supervisor and sub-agents|
|5140|2025-12-06|tool|always-on|NEW (proposed) `trig-workdir`: copy of EXISTING `misleading-error` (has an `app/` subdir),|yes|tweak: make bash give agent more awareness of cwd, bump default timeout, drop max timeout|
|5222|2025-12-07|tool|always-on|trig-read-lines|no|pdf support in read tool|
|5229|2025-12-08|tool|conditional|make-it-run; verify which tool|no|add ocamlformat support|
|5157|2025-12-09|subagent/agent|conditional|make-it-run; verify which tool|no|feat: add CLI arguments to agent create command for scripting|
|5298|2025-12-09|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|better interleaved thinking support|
|5334|2025-12-10|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|more interleaved thinking fixes|
|5521|2025-12-14|provider-format|always-on|trig-read-lines|no|Provider fix, anthropic Errorhandling if empty image file is read|
|5542|2025-12-14|loop|always-on|any existing task (make-it-run)|no|feat: restore experimental.chat.messages.transform and add experimental.chat.system.transform hooks|
|5462|2025-12-14|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|LLM cleanup|
|4729|2025-12-14|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|feat: add experimental.continue_loop_on_deny config option|
|5527|2025-12-14|loop|conditional|EXISTING `make-it-run` plus proxy fault injection: on the first request, the Vertex proxy |yes|feat: add server_error, rate_limit, and no_kv_space retry logic to accommodate Foundry API issues|
|5642|2025-12-16|subagent/agent|conditional|trig-subagent-resume|no|plugin(hook): add task tool execution hooks and command context tracking|
|5650|2025-12-16|loop|always-on|any existing task (make-it-run)|no|fix: user invoked subtasks causing tool_use or missing thinking signa…|
|5620|2025-12-16|tool|conditional|make-it-run; verify which tool|no|feat: add experimental oxfmt formatter|
|5633|2025-12-16|loop|always-on|any existing task (make-it-run)|no|fix: use system prompt field from prompt input|
|5698|2025-12-17|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|feat(plugin): add experimental.session.compacting hook for pre-compaction context injection|
|5679|2025-12-17|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|add OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX to override 32k default|
|5659|2025-12-17|tool|needs-new-task|NEW trig-batch: task needing many independent reads, batch tool enabled|no|batch: enable edit, todoread, clarify error message, minor tool description change|
|5676|2025-12-17|tool|always-on|trig-bash-limits|no|fix: remove unsupported parameter from bash tool description|
|5740|2025-12-18|loop|always-on|any existing task (make-it-run)|no|fix(command): validate model before executing slash command|
|5881|2025-12-20|subagent/agent|conditional|make-it-run; verify which tool|no|core: add verification that at least 1 primary agent is enabled, add regression tests|
|5843|2025-12-20|subagent/agent|conditional|make-it-run; verify which tool|no|feat: support configuring a default_agent across all API/user surfaces|
|5921|2025-12-21|prompt|always-on|any existing task (make-it-run)|no|feat: add Agent Skills support|
|5907|2025-12-22|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|feat(plugin): allow compaction hook to replace prompt entirely|
|6000|2025-12-22|loop|conditional|trig-skills|no|feat(skill): add per-agent filtering to skill tool description|
|5930|2025-12-22|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|feat: add native skill tool with permission system|
|5933|2025-12-22|tool|conditional|trig-lsp-ts|no|feat(lsp): add Tinymist LSP support for Typst|
|5886|2025-12-22|tool|conditional|trig-lsp-ts|no|feat: add experimental lsp tool|
|6175|2025-12-25|tool|always-on|make-ci-green|no|fix: only show diagnostics block when errors exist|
|6141|2025-12-25|tool|conditional|trig-lsp-ts|no|feat: haskell lsp support|
|6193|2025-12-26|prompt|always-on|any existing task (make-it-run)|no|chore: kill the dead Polaris Alpha code|
|6196|2025-12-26|tool|always-on|trig-grep-trunc|no|doc: fix typos in various files|
|6238|2025-12-27|tool|always-on|trig-bash-limits|no|doc: fix typos in various files|
|6252|2025-12-28|tool|conditional|make-it-run; verify which tool|no|feat: add support for `.claude/skills` directory|
|6294|2025-12-28|tool|always-on|trig-omp-findext|no|doc: fix typos in various files|
|6420|2025-12-29|tool|conditional|make-it-run; verify which tool|no|tweak: read global claude skills too|
|6325|2025-12-29|loop|always-on|any existing task (make-it-run)|no|feat: add variants toggle|
|6345|2025-12-29|tool|conditional|trig-webfetch-image|no|fix(webfetch): make format parameter optional with markdown default|
|6383|2025-12-29|session-other|always-on|any existing task (make-it-run)|no|fix: filter messages with only step-start parts in toModelMessage|
|6481|2025-12-30|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|fix: ensure variants also work for completely custom models|
|6463|2025-12-30|loop|always-on|any existing task (make-it-run)|no|feat: add extract reasoning middleware|
|6429|2025-12-30|subagent/agent|conditional|trig-todo-task|no|chore: fix various typos|
|6524|2025-12-31|lsp/diagnostics|conditional|EXISTING `make-it-run`, unchanged. Read and edit call LSP.touchFile on `.py` files, and th|yes|Add support for LSP workspace/didChangeWatchedFiles|
|5767|2025-12-31|loop|always-on|any existing task (make-it-run)|no|feat: mcp prompts as slash commands (alternative)|
|6319|2026-01-01|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|Permission rework|
|6480|2026-01-01|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(session): check for context overflow mid-turn in finish-step|
|6578|2026-01-01|loop|always-on|any existing task (make-it-run)|no|fix: display error if invalid agent is used in a command|
|6725|2026-01-02|loop|always-on|any existing task (make-it-run)|no|core: ephemerally wrap queued user messages with reminder to stay on track|
|6601|2026-01-02|tool|conditional|trig-lsp-ts|no|feat: Add kotlin lsp integration|
|6687|2026-01-02|prompt|always-on|any existing task (make-it-run)|no|chore: rename repo references from sst/opencode to anomalyco/opencode|
|6542|2026-01-04|loop|always-on|any existing task (make-it-run)|no|feat: mcp resources|
|6525|2026-01-05|loop|always-on|any existing task (make-it-run)|no|fix: pass image parts to custom commands|
|4773|2026-01-06|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|Added: Ability to hide subagents from primary agents system prompt.|
|7128|2026-01-06|prompt|always-on|any existing task (make-it-run)|no|adding timeout|
|7125|2026-01-06|prompt|always-on|any existing task (make-it-run)|no|feat: url based instructions|
|7115|2026-01-06|prompt|always-on|any existing task (make-it-run)|no|load `OPENCODE_CONFIG_DIR` AGENTS.md into the system prompt|
|7042|2026-01-06|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix: restore skill filtering by agent permissions|
|7268|2026-01-07|subagent/agent|needs-new-task|NEW trig-question: underspecified task where the right move is to ask; harness auto-answer|no|core: add interactive question tool for gathering user preferences and clarifying instructions|
|7239|2026-01-07|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|feat: write truncated tool outputs to files|
|7386|2026-01-08|tool|needs-new-task|NEW trig-question: underspecified task where the right move is to ask; harness auto-answer|no|feat(question): support multi-select questions|
|7205|2026-01-08|prompt|always-on|any existing task (make-it-run)|no|feat(flags): allow disabling .claude prompt and skills loading|
|7718|2026-01-10|loop|always-on|any existing task (make-it-run)|no|feat: pass sessionID to chat.system.transform|
|7501|2026-01-10|tool|always-on|trig-grep-trunc|no|fix(grep): follow symlinks by default in ripgrep searches|
|8111|2026-01-12|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix(task): respect agent task permission for nested sub-agents|
|8092|2026-01-12|provider-format|always-on|any existing task (Anthropic path)|no|fix(bedrock): use reasoningConfig for Anthropic models on Bedrock|
|8090|2026-01-12|session-other|conditional|make-it-run (path fires only on specific events; see diff)|no|fix(session): store api url in metadata|
|8281|2026-01-13|subagent/agent|conditional|trig-plan-subagent|no|feat: add plan mode with enter/exit tools|
|8778|2026-01-15|tool|needs-new-task|NEW trig-question: underspecified task where the right move is to ask; harness auto-answer|no|docs: clarify question tool guidance|
|7681|2026-01-15|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|fix: stop changing main model/agent from subtasks invocation|
|8678|2026-01-15|subagent/agent|conditional|make-it-run; verify which tool|no|fix(agent): default agent selection in acp and headless mode|
|8658|2026-01-15|loop|always-on|any existing task (make-it-run)|no|feat: add litellmProxy provider option for explicit LiteLLM compatibility|
|8612|2026-01-15|tool|always-on|trig-grep-trunc|no|fix: handle broken symlinks gracefully in grep tool|
|8465|2026-01-15|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(opencode): add input limit for compaction|
|8944|2026-01-16|loop|always-on|any existing task (make-it-run)|no|Revert "fix: ensure that tool attachments arent sent as user messages (#8944)"|
|8944|2026-01-16|loop|always-on|any existing task (make-it-run)|no|fix: ensure that tool attachments arent sent as user messages|
|9517|2026-01-19|tool|needs-new-task|NEW trig-batch: task needing many independent reads, batch tool enabled|no|fix(batch): update batch tool definition to outline correct value for max tool calls|
|9275|2026-01-19|tool|needs-new-task|NEW trig-batch: task needing many independent reads, batch tool enabled|no|tweak(batch): up restrictive max batch tool from `10` to `25`|
|9436|2026-01-19|tool|conditional|make-it-run; verify which tool|no|fix(opencode): `cargo fmt` is formatting whole workspace instead of edited file|
|8093|2026-01-20|prompt|always-on|any existing task (make-it-run)|no|feat: add OPENCODE_DISABLE_PROJECT_CONFIG env var|
|9935|2026-01-21|loop|always-on|any existing task (make-it-run)|no|fix: correct spelling 'supercedes' to 'supersedes'|
|9813|2026-01-21|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|feat: implement home directory expansion for permission patterns using `~` and `$HOME` prefixes.|
|9838|2026-01-21|provider-format|always-on|any existing task (Anthropic path)|no|fix: Claude w/bedrock custom inference profile - caching support|
|7312|2026-01-21|tool|conditional|make-it-run; verify which tool|no|feat(formatters): add laravel pint as a `.php` formatter|
|9953|2026-01-22|provider-format|always-on|any existing task (Anthropic path)|no|fix(provider): add thinking presets for Google Vertex Anthropic|
|10442|2026-01-24|provider-format|always-on|any existing task (Anthropic path)|no|fix(provider): enable thinking for google-vertex-anthropic models|
|10323|2026-01-24|provider-format|always-on|any existing task (make-it-run)|no|fix(provider): deep merge providerOptions in applyCaching|
|10678|2026-01-26|loop|always-on|trig-read-lines|no|feat: dynamically resolve AGENTS.md files from subdirectories as agent explores them|
|10680|2026-01-26|subagent/agent|conditional|make-it-run; verify which tool|no|feat(opencode): add agent description|
|10995|2026-01-28|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|fix: maxOutputTokens was accidentally hardcoded to undefined|
|10833|2026-01-28|loop|always-on|trig-omp-findext|no|fix(opencode): add `AbortSignal` support to `Ripgrep.files()` and `GlobTool`|
|10990|2026-01-28|session-other|conditional|make-it-run (path fires only on specific events; see diff)|no|fix: add SubtaskPart with metadata reference|
|9640|2026-01-29|tool|conditional|trig-skills|no|feat: support config skill registration|
|11415|2026-01-30|tool|always-on|trig-grep-trunc|no|fix: don't --follow by default for grep and other things using ripgrep|
|11363|2026-01-30|provider-format|conditional|make-it-run (path fires only on specific events; see diff)|no|fix(provider): exclude chat models from textVerbosity setting|
|11520|2026-01-31|loop|conditional|make-it-run + proxy fault injection (method used for #3369/#5527)|no|tweak: show actual retry error message instead of generic error msg|
|11731|2026-02-01|prompt|always-on|EXISTING `make-it-run`, unchanged (always-on).|yes|Simplify directory tree output for prompts|
|11410|2026-02-01|subagent/agent|conditional|make-it-run; verify which tool|no|fix(opencode): scope agent variant to model|
|11844|2026-02-02|loop|always-on|trig-read-lines|no|Revert pr that was mistakenly merged|
|11842|2026-02-03|tool|conditional|make-it-run; verify which tool|no|feat: add support for reading skills from .agents/skills directories|
|11984|2026-02-03|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|fix: ensure mcp tools are sanitized|
|11737|2026-02-03|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|feat: improve skills, better prompting, fix permission asks after invoking skills, ensure agent knows where scripts/resources are|
|11536|2026-02-04|prompt|conditional|make-it-run (path fires only on specific events; see diff)|no|fix: prioritize OPENCODE_CONFIG_DIR for AGENTS.md|
|12369|2026-02-05|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|core: fix unhandled errors when aborting with queued messages|
|12214|2026-02-05|subagent/agent|conditional|Same `trig-subagent-resume` as #4204 (the prompt says "the id the first call returned", so|yes|tweak: adjust task tool description/input to alleviate tool call failures that sometimes occured w/ gpt models|
|12531|2026-02-06|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|feat(core): Set variant in assistant messages too|
|10987|2026-02-06|loop|always-on|trig-bash-limits|no|fix(opencode): SessionPrompt.shell() now triggers loop if messages are queued|
|12144|2026-02-06|prompt|always-on|any existing task (make-it-run)|no|feat: add specific system prompt for Trinity model|
|12924|2026-02-10|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(core): ensure compaction is more reliable, add reserve token buffer to ensure that input window has enough room to compact|
|12852|2026-02-10|tool|always-on|trig-bash-limits|no|chore: fix typos and GitHub capitalization|
|13214|2026-02-11|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|tweak: compaction check|
|13198|2026-02-11|loop|always-on|Same `trig-read-edge` as #13090. Step (c), offset 3, shows line `3:` first on the merge bu|yes|tweak: make read tool offset 1 indexed instead of 0 to avoid confusion that could be caused by line #s being 1 based|
|13090|2026-02-11|tool|always-on|NEW (proposed) `trig-read-edge`: copy of EXISTING `make-ci-green`, instruction prefixed wi|yes|feat: adjust read tool so that it can handle dirs too|
|13428|2026-02-12|loop|conditional|trig-list|no|fix: ensure @-ing a dir uses the read tool instead of dead list tool|
|4956|2026-02-12|tool|conditional|make-it-run; verify which tool|no|feat(hook): add tool.definition hook for plugins to modify tool description and parameters|
|13331|2026-02-12|tool|conditional|NEW (proposed) `trig-webfetch-image`: tiny workspace whose `answer.txt` must name the domi|yes|feat(tool): return image attachments from webfetch|
|13269|2026-02-12|tool|always-on|NEW (proposed) `trig-grep-trunc`: copy of EXISTING `taskflow`, instruction prefixed with "|yes|tweak: tool outputs to be more llm friendly|
|13559|2026-02-13|tool|needs-new-task|NEW trig-websearch: task whose fix needs a fact only on the web (e.g. pin a library versio|no|fix: tweak websearch tool description date info to avoid cache busts|
|13498|2026-02-14|provider-format|always-on|any existing task (Anthropic path)|no|fix: ensure anthropic models on OR also have variant support|
|13915|2026-02-16|loop|always-on|any existing task (make-it-run)|no|core: keep message part order stable when files resolve asynchronously|
|13890|2026-02-16|loop|conditional|trig-webfetch-image|no|tweak: drop ids from attachments in tools, assign them in prompt.ts instead|
|13804|2026-02-16|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(core): remove unnecessary per-message title LLM calls|
|14060|2026-02-17|subagent/agent|conditional|make-it-run; verify which tool|no|fix: ensure explore subagent has external_directory perm set to ask instead of auto denying|
|14009|2026-02-17|tool|always-on|trig-read-lines|no|fix: make read tool more mem efficient|
|14345|2026-02-19|loop|always-on|any existing task (make-it-run)|no|fix: add missing id/sessionID/messageID to MCP tool attachments|
|14354|2026-02-19|loop|always-on|any existing task (make-it-run)|no|remove unnecessary deep clones from session loop and LLM stream|
|14283|2026-02-19|provider-format|always-on|any existing task (Anthropic path)|no|feat(opencode): support adaptive thinking for claude sonnet 4.6|
|14215|2026-02-19|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|Remove use of Bun.file|
|14707|2026-03-02|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix: recover from 413 Request Entity Too Large via auto-compaction|
|15928|2026-03-03|tool|always-on|trig-bash-limits|no|docs(bash): clarify output capture guidance|
|9443|2026-03-07|tool|always-on|make-ci-green|no|fix(opencode): preserve original line endings in 'edit' tool|
|17098|2026-03-11|tool|conditional|NEW (proposed) `trig-skills`: copy of EXISTING `make-it-run` plus `.claude/skills/python-r|yes|tweak: adjust skill presentation to be a little less token heavy|
|17053|2026-03-11|loop|conditional|EXISTING `make-it-run`, unchanged (always-on). For the intended effect (more skill invocat|yes|tweak: adjust way skills are presented to agent to increase likelyhood of skill invocations.|
|17064|2026-03-15|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix(opencode): preserve prompt tool enables with empty agent permissions|
|17823|2026-03-16|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(opencode): apply message transforms during compaction|
|18165|2026-03-18|loop|always-on|any existing task (make-it-run)|no|fix(session): preserve tagged error messages|
|18140|2026-03-18|prompt|always-on|None with Opus 5.5 as configured: system.ts routes any `model.api.id` containing "claude" |yes|tweak: remove unnecessary parts from the fallback system prompt|
|18292|2026-03-19|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix: avoid truncate permission import cycle|
|18261|2026-03-19|subagent/agent|conditional|trig-subagent-resume|no|fix: stabilize agent and skill ordering in prompt descriptions|
|18186|2026-03-19|prompt|always-on|any existing task (make-it-run)|no|anthropic legal requests|
|18438|2026-03-20|subagent/agent|conditional|trig-subagent-resume|no|fix: switch consumers to service imports to break bundle cycles|
|19125|2026-03-25|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix(task): respect agent permission config for todowrite tool|
|19128|2026-03-25|subagent/agent|conditional|trig-todo-task|no|chore: remove dead code for todoread tool|
|17814|2026-03-25|loop|always-on|any existing task (make-it-run)|no|feat(core): initial implementation of syncing|
|19058|2026-03-25|lsp/diagnostics|conditional|NEW (proposed) `trig-lsp-outside`: copy of EXISTING `make-it-run`, instruction prefixed wi|yes|tweak: only spawn lsp servers for files in current instance (or cwd if instance is global)|
|19487|2026-03-27|tool|always-on|trig-bash-limits|no|tweak: adjust bash tool description to increase cache hit rates between projects|
|18539|2026-03-29|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix: discourage _noop tool call during LiteLLM compaction|
|19924|2026-03-29|prompt|conditional|make-it-run (path fires only on specific events; see diff)|no|fix: ensure OPENCODE_DISABLE_CLAUDE_CODE_PROMPT is respected for project lvl CLAUDE.md|
|16069|2026-03-30|loop|always-on|trig-read-lines|no|feat(windows): add first-class pwsh/powershell support|
|20266|2026-03-31|provider-format|always-on|any existing task (Anthropic path)|no|feat: enable prompt caching and cache token tracking for google-vertex-anthropic|
|20581|2026-04-01|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(session): compaction agent responds in same language as conversation|
|20702|2026-04-02|loop|always-on|any existing task (make-it-run)|no|ignore: fix typecheck in dev|
|20657|2026-04-02|loop|always-on|any existing task (make-it-run)|no|feat: add optional messageID to ShellInput|
|20771|2026-04-03|tool|always-on|trig-bash-limits|no|fix: rm dynamic part from bash tool description again to restore cache hits across projects|
|21070|2026-04-05|tool|always-on|EXISTING `make-it-run`, unchanged (the agent reads main.py/greeter.py).|yes|tweak: add newline between <content> and first line of read tool output to prevent confusion|
|21225|2026-04-06|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|tweak: move the max token exclusions to plugins  @rekram1-node|
|21220|2026-04-06|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|tweak: adjust chat.params hook to allow altering of the maxOutputTokens|
|21052|2026-04-07|subagent/agent|needs-new-task|NEW trig-websearch: task whose fix needs a fact only on the web (e.g. pin a library versio|no|core: refactor tool system to remove agent context from initialization|
|21355|2026-04-07|loop|conditional|make-it-run + proxy fault injection (method used for #3369/#5527)|no|fix: ensure the alibaba provider errors are retried|
|21332|2026-04-07|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(opencode): keep user message variants scoped to model|
|21466|2026-04-08|tool|conditional|trig-lsp-ts|no|fix(lsp): remove CMakeLists.txt and Makefile from clangd root markers|
|21584|2026-04-08|loop|always-on|trig-read-lines|no|fix: propagate abort signal to inline read tool|
|21724|2026-04-09|loop|always-on|trig-bash-limits|no|fix: finalize interrupted bash via tool result path|
|21598|2026-04-09|loop|always-on|trig-bash-limits|no|fix: preserve interrupted bash output in tool results|
|21583|2026-04-09|loop|conditional|make-it-run + proxy fault injection (method used for #3369/#5527)|no|feat: add opencode go upsell modal when limits are hit|
|17803|2026-04-09|provider-format|always-on|any existing task (Anthropic path)|no|Remove CLI from electron app|
|21958|2026-04-10|loop|always-on|any existing task (make-it-run)|no|tweak: rm processor .trim calls|
|22168|2026-04-12|session-other|always-on|trig-read-lines|no|fix: ensure images read by agent dont count against quota|
|22361|2026-04-13|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|feat: add experimental.compaction.autocontinue hook to disable auto continuing after compaction|
|22356|2026-04-13|tool|always-on|trig-omp-findext|no|fix grep exact file path searches|
|22249|2026-04-13|provider-format|always-on|any existing task (Anthropic path)|no|fix: forgot to put alibaba case in last commit|
|22248|2026-04-13|provider-format|always-on|any existing task (Anthropic path)|no|feat: add alibaba pkg and cache support|
|22390|2026-04-14|loop|conditional|Same `trig-bash-limits` as #5066 (step 2 forces a 2000 ms timeout).|yes|improve bash timeout retry hint|
|22694|2026-04-15|provider-format|conditional|make-it-run (path fires only on specific events; see diff)|no|fix: prefix 32 unused parameters with underscore|
|22672|2026-04-15|tool|conditional|make-it-run; verify which tool|no|fix(core): Remove dead code and documentation related to the obsolete list tool.|
|22646|2026-04-15|provider-format|always-on|any existing task (Anthropic path)|no|fix: ensure tool_use is always followed by tool_result|
|22827|2026-04-16|tool|conditional|make-it-run; verify which tool|no|fix: preserve plugin tool metadata in execute result|
|22882|2026-04-16|loop|conditional|trig-lsp-ts|no|fix: remove 10 more unnecessary `as any` casts in opencode core|
|22873|2026-04-16|provider-format|conditional|make-it-run (path fires only on specific events; see diff)|no|tweak: set display 'summarized' by default for opus 4.7 thorugh messages api|
|22833|2026-04-16|provider-format|always-on|any existing task (Anthropic path)|no|feat: Add support for claude opus 4.7 xhigh adaptive reasoning effort|
|23253|2026-04-17|tool|conditional|trig-skills|no|fix: make skills logic more token efficient|
|23291|2026-04-18|tool|conditional|trig-webfetch-image|no|fix: detect attachment mime from file contents|
|22773|2026-04-19|tool|conditional|make-it-run; verify which tool|no|fix(ripgrep): restore native rg backend|
|23491|2026-04-20|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|tweak: rename tail_tokens -> preserve_recent_tokens|
|23483|2026-04-20|tool|always-on|make-ci-green|no|fix: parallel edits sometimes would override each other|
|23701|2026-04-21|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|chore: kill unused tool|
|23770|2026-04-23|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|feat(truncate): allow configuring tool output truncation limits|
|23771|2026-04-23|tool|conditional|NEW (proposed) `trig-lsp-csharp`: minimal `.csproj` + `Program.cs` with one compile error |yes|feat: support pull diagnostics in the LSP client (C#, Kotlin, etc)|
|23870|2026-04-23|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(session): improve session compaction|
|23797|2026-04-23|tool|needs-new-task|NEW trig-patch: multi-file edit task with patch tool enabled for Claude (normally GPT-only|no|fix: preserve BOM in text tool round-trips|
|19937|2026-04-24|tool|always-on|trig-bash-limits|no|fix(opencode): clarify git amend condition to require verifying commit landed|
|24222|2026-04-25|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix permission config order|
|24139|2026-04-25|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|tool/lsp: include request details in permission metadata|
|24574|2026-04-26|provider-format|always-on|any existing task (Anthropic path)|no|ignore: split up reasoning transforms|
|24573|2026-04-26|provider-format|always-on|any existing task (Anthropic path)|no|fix: default tool call streaming to false for google vertex|
|24677|2026-04-27|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(session): remove compaction summary dividers|
|24553|2026-04-27|loop|always-on|trig-bash-limits|no|fix(session): harden shell cancellation|
|24576|2026-04-27|tool|conditional|trig-lsp-ts|no|fix: pass workspace symbol query to experimental LSP tool|
|23290|2026-04-29|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix(opencode): preserve `external_dir` and `deny` parent permissions in task child sessions|
|24992|2026-04-29|subagent/agent|needs-new-task|NEW trig-codesearch: task needing an external library API lookup, codesearch tool enabled|no|chore: rm broken codesearch tool|
|24974|2026-04-29|prompt|always-on|NEW (proposed) `trig-prompt-order`: copy of EXISTING `make-it-run` plus a project `AGENTS.|yes|tweak: adjust order of system prompt instructions: Global, Project, Skills|
|25226|2026-04-30|subagent/agent|always-on|NEW (proposed) `trig-tmpdir`: copy of EXISTING `make-it-run`, instruction prefixed with "D|yes|Preapprove agent tmp directory access|
|25145|2026-04-30|provider-format|always-on|any existing task (Anthropic path)|no|fix(provider): split providerOptions key on dot for openai-compatible, openai, and anthropic providers|
|25123|2026-04-30|tool|conditional|make-it-run; verify which tool|no|fix: ensure disabling OPENCODE_DISABLE_CLAUDE_CODE_SKILLS doesnt disable external skills too|
|25241|2026-05-01|session-other|conditional|make-it-run (path fires only on specific events; see diff)|no|fix: fix issue if tool returned image and empty text and it caused api errors|
|25431|2026-05-02|tool|always-on|Same `trig-read-edge` as #13090 (step (b) reads with offset 0).|yes|tweak: allow read tool to accept offset of 0|
|20039|2026-05-03|loop|always-on|trig-bash-limits|no|feat: refactor bash tool with shell-aware prompts for bash, pwsh+powershell, and cmd|
|25798|2026-05-04|subagent/agent|conditional|trig-subagent-resume|no|fix(session): cancel subtask child sessions|
|25934|2026-05-05|provider-format|always-on|any existing task (make-it-run)|no|fix: sanitize surrogates|
|25851|2026-05-05|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(compaction): order compaction summary before retained tail|
|25634|2026-05-05|loop|always-on|any existing task (make-it-run)|no|Improve v2 session message rendering|
|21370|2026-05-06|provider-format|always-on|any existing task (Anthropic path)|no|fix(provider): preserve assistant message content when reasoning blocks present|
|26276|2026-05-07|provider-format|always-on|any existing task (Anthropic path)|no|fix: tweaks to transform logic for anthropic and bedrock|
|24149|2026-05-08|subagent/agent|needs-new-task|NEW trig-codesearch: task needing an external library API lookup, codesearch tool enabled|no|feat(core): add scout agent for repo research|
|26391|2026-05-08|tool|conditional|make-it-run; verify which tool|no|fix(skill): allow missing descriptions|
|26227|2026-05-08|tool|needs-new-task|NEW trig-websearch: task whose fix needs a fact only on the web (e.g. pin a library versio|no|feat(websearch): add parallel provider rollout|
|26275|2026-05-08|provider-format|conditional|make-it-run (path fires only on specific events; see diff)|no|fix(provider): align Anthropic Opus 4.5 efforts|
|26620|2026-05-09|session-other|always-on|any existing task (make-it-run)|no|fix(session): tolerate negative token counts in stored parts|
|26617|2026-05-09|tool|conditional|make-it-run; verify which tool|no|feat(skill): built-in opencode-meta skill|
|26597|2026-05-09|subagent/agent|conditional|trig-subagent-resume|no|fix(task): subagent inherits parent agent's deny rules (Plan Mode security bypass)|
|25667|2026-05-09|session-other|conditional|make-it-run (path fires only on specific events; see diff)|no|research: delete Hono backend (do not merge)|
|26739|2026-05-10|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|Drop compaction create facade|
|26692|2026-05-10|subagent/agent|always-on|trig-omp-findext|no|feat(scout): materialize configured reference repos|
|26401|2026-05-10|loop|always-on|any existing task (make-it-run)|no|feat: better image handling (auto resize & max size constraints)|
|26958|2026-05-11|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix: grep external directory permission evaluation|
|26843|2026-05-11|loop|always-on|any existing task (make-it-run)|no|feat(scout): autocomplete configured mentions|
|26830|2026-05-11|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|feat(compaction): serialize compaction tail|
|27258|2026-05-12|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|temporarily revert: preserve permission ordering by accepting a layered array|
|27248|2026-05-12|loop|always-on|any existing task (make-it-run)|no|fix: disable image module for now|
|23214|2026-05-12|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix: preserve permission ordering by accepting a layered array|
|27157|2026-05-12|tool|conditional|make-it-run; verify which tool|no|fix(plugin): preserve tool attachments|
|27145|2026-05-12|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(compaction): restore tail turns after summarization|
|27019|2026-05-12|subagent/agent|needs-new-task|NEW trig-codesearch: task needing an external library API lookup, codesearch tool enabled|no|chore: remove codesearch tool|
|26805|2026-05-13|loop|always-on|any existing task (make-it-run)|no|fix: image resizer wasm loading, reenable image resizing|
|25821|2026-05-13|loop|always-on|any existing task (make-it-run)|no|core: expose v2 model listing API|
|27280|2026-05-13|subagent/agent|conditional|trig-subagent-resume|no|fix(session): use typed message reads in tools|
|27269|2026-05-13|session-other|always-on|any existing task (make-it-run)|no|fix(session): add typed message lookup wrappers|
|26309|2026-05-13|tool|conditional|trig-webfetch-image|no|fix: use htmlrewriter2 instead of HTMLRewriter for node compat|
|27201|2026-05-13|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix(task): preserve subagent self permissions|
|27084|2026-05-14|subagent/agent|conditional|trig-subagent-resume|no|feat: add experimental background subagents|
|27254|2026-05-14|loop|always-on|any existing task (make-it-run)|no|fix(session): finalize interrupted assistant messages|
|27872|2026-05-16|subagent/agent|conditional|trig-subagent-resume|no|fix: hide task background instructions by default|
|26821|2026-05-16|subagent/agent|conditional|NEW (proposed) `trig-todo-task`: copy of EXISTING `make-ci-green`, instruction prefixed wi|yes|core: reduce prompts for shell, todowrite, and task tools|
|27114|2026-05-18|prompt|always-on|any existing task (make-it-run)|no|Preview native LLM runtime stack|
|28082|2026-05-18|prompt|always-on|any existing task (make-it-run)|no|refactor(session): move prompt reminders out of core loop|
|28357|2026-05-19|tool|conditional|make-it-run; verify which tool|no|fix(tool): tolerate plugin tool defs with missing args|
|28678|2026-05-21|session-other|conditional|make-it-run (path fires only on specific events; see diff)|no|fix(llm): preserve native continuation metadata|
|28998|2026-05-23|tool|always-on|trig-bash-limits|no|fix(opencode): advertise configured shell timeout|
|29179|2026-05-25|subagent/agent|conditional|trig-subagent-resume|no|remove the need for polling from experimental background agents|
|26178|2026-05-25|loop|always-on|any existing task (make-it-run)|no|fix(session): exclude orphaned interrupted tools from run-loop continuation|
|29769|2026-05-28|provider-format|always-on|any existing task (Anthropic path)|no|fix(opencode): enable adaptive reasoning for opus 4.7+|
|29911|2026-05-29|provider-format|always-on|any existing task (Anthropic path)|no|fix(opencode): support vertex opus adaptive reasoning|
|29991|2026-05-30|provider-format|always-on|any existing task (Anthropic path)|no|fix(opencode): support sap-ai-core anthropic opus 4.7+ adaptive reasoning|
|30127|2026-05-31|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(opencode): remove automatic full session diffs|
|30483|2026-06-02|provider-format|always-on|any existing task (Anthropic path)|no|fix: rm tool reorder logic from old bug|
|30485|2026-06-02|subagent/agent|conditional|trig-subagent-resume|no|fix: task id passed to background job for continuation|
|30435|2026-06-02|subagent/agent|conditional|make-it-run; verify which tool|no|chore(opencode): remove scout agent|
|30287|2026-06-02|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|feat(core): add location-based permission service|
|30632|2026-06-03|subagent/agent|conditional|trig-webfetch-image|no|feat(core): add embedded v2 session runtime and tool foundation|
|30617|2026-06-03|subagent/agent|conditional|trig-skills|no|feat(core): add skill registry and file agent loading|
|30789|2026-06-04|prompt|always-on|any existing task (make-it-run)|no|feat(core): persist v2 session context epochs|
|30832|2026-06-04|loop|conditional|trig-webfetch-image|no|feat(core): attach global native tools|
|30790|2026-06-04|subagent/agent|conditional|trig-subagent-resume|no|tweak: background agent prompting to avoid polling issues|
|30640|2026-06-04|session-other|always-on|any existing task (make-it-run)|no|feat(core): moving sessions|
|30749|2026-06-04|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(opencode): respect disabled auto compaction on overflow|
|30624|2026-06-04|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|feat(core): add command registry|
|30687|2026-06-04|subagent/agent|conditional|trig-subagent-resume|no|refactor(opencode): clean up task tool prompts|
|31038|2026-06-05|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(core): make V2 reads media-aware and binary-safe|
|31036|2026-06-05|loop|always-on|any existing task (make-it-run)|no|fix(core): scope v2 prompt cache by session|
|31005|2026-06-05|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(core): recover v2 context overflow|
|30999|2026-06-05|loop|conditional|trig-webfetch-image|no|feat(core): bound v2 tool output|
|30990|2026-06-05|loop|always-on|any existing task (make-it-run)|no|fix(core): preserve model request semantics|
|30986|2026-06-05|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|feat(core): compact v2 session context|
|30982|2026-06-05|subagent/agent|conditional|make-it-run; verify which tool|no|feat(core): honor default session models|
|30850|2026-06-05|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|feat(core): interrupt v2 session execution|
|30843|2026-06-05|subagent/agent|conditional|trig-skills|no|feat(core): admit v2 skill guidance|
|30973|2026-06-05|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(opencode): gate reasoning summaries by provider|
|30969|2026-06-05|subagent/agent|conditional|make-it-run; verify which tool|no|fix(core): respect v2 default agents|
|31171|2026-06-06|loop|conditional|trig-webfetch-image|no|fix(core): harden unified tool runtime|
|31165|2026-06-06|tool|always-on|trig-read-lines|no|fix(core): isolate image normalization|
|31162|2026-06-06|subagent/agent|conditional|trig-subagent-resume|no|fix: background agent prompting, lets kill this sleep behavior oml|
|27802|2026-06-06|tool|always-on|trig-omp-findext|no|feat(opencode): fff search tools|
|31061|2026-06-06|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix(core): enforce V2 tool permissions|
|31062|2026-06-06|loop|always-on|any existing task (make-it-run)|no|fix(core): bound prompt cache session keys|
|31269|2026-06-07|tool|conditional|make-it-run; verify which tool|no|fix(opencode): avoid duplicate skill catalog|
|31394|2026-06-08|subagent/agent|conditional|trig-subagent-resume|no|fix(session): avoid sticky prompt tool overrides|
|30529|2026-06-08|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix(session): merge per-call tool rules into session permission|
|28761|2026-06-08|tool|conditional|trig-lsp-ts|no|fix(lsp): resolve JDTLS root to topmost pom.xml in Java Maven multi-module projects|
|31531|2026-06-09|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|feat(opencode): add typed application layer graph|
|31546|2026-06-09|provider-format|always-on|any existing task (Anthropic path)|no|fix(opencode): support Claude Fable reasoning|
|31696|2026-06-10|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix(opencode): let subagents use their own permissions|
|31601|2026-06-10|prompt|always-on|any existing task (make-it-run)|no|feat(core): add project reference guidance|
|31745|2026-06-11|loop|always-on|any existing task (make-it-run)|no|fix(opencode): surface content-filter finish reason as visible error|
|33142|2026-06-20|loop|always-on|any existing task (make-it-run)|no|fix(core): honor configured agent step limits|
|33266|2026-06-21|loop|always-on|any existing task (make-it-run)|no|fix(core): settle interrupted assistant steps|
|33260|2026-06-21|tool|always-on|trig-read-lines|no|fix(core): handle read file failures|
|33452|2026-06-22|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|fix(core): reset steps for promoted prompts|
|33377|2026-06-22|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|fix(core): defer session model validation|
|33530|2026-06-23|provider-format|always-on|any existing task (make-it-run)|no|fix(core): preserve structured error messages|
|33483|2026-06-23|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|feat(mcp): add resource read tools|
|33562|2026-06-24|provider-format|always-on|any existing task (make-it-run)|no|feat(core): map providers to integrations|
|33546|2026-06-24|mcp|needs-new-task|NEW trig-mcp: task requiring a stub MCP server tool|no|feat(mcp): add resource template listing|
|34059|2026-06-26|tool|conditional|make-it-run; verify which tool|no|fix(core): refresh cached remote skills|
|34052|2026-06-26|tool|conditional|make-it-run; verify which tool|no|fix(opencode): preserve skill resource paths|
|34673|2026-06-30|provider-format|always-on|any existing task (Anthropic path)|no|fix(provider): enable sonnet 5 adaptive thinking|
|35077|2026-07-02|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|revert: back out experimental codemode|
|34677|2026-07-02|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|feat: experimental codemode|
|35185|2026-07-03|loop|conditional|make-it-run (path fires only on specific events; see diff)|no|feat(opencode): gate execute tool behind code mode flag|
|35085|2026-07-03|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|feat(opencode): add code-mode MCP adapter|
|35356|2026-07-04|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix(core): stop after declined permissions|
|35452|2026-07-06|tool|conditional|make-it-run; verify which tool|no|fix(codemode): unify catalog signatures|
|36122|2026-07-09|prompt|always-on|any existing task (make-it-run)|no|feat: add meta muse system prompt|
|36626|2026-07-13|provider-format|conditional|make-it-run (path fires only on specific events; see diff)|no|fix(provider): tweak reasoning option driven max budget variants|
|36624|2026-07-13|provider-format|always-on|any existing task (Anthropic path)|no|fix(provider): derive variants from reasoning metadata|
|36976|2026-07-14|provider-format|always-on|any existing task (make-it-run)|no|fix(opencode): default Meta reasoning to xhigh|
|37124|2026-07-15|subagent/agent|conditional|trig-subagent-resume|no|fix(core): limit subagent nesting depth|
|37519|2026-07-17|provider-format|always-on|any existing task (Anthropic path)|no|fix(provider): honor reasoning option semantics|
|38757|2026-07-24|provider-format|always-on|any existing task (Anthropic path)|no|fix(provider): generalize Claude adaptive thinking|
|39259|2026-07-28|tool|conditional|make-it-run; verify which tool|no|fix(mcp): honor callback port in debug|
|40707|2026-08-05|loop|conditional|make-it-run + proxy fault injection (method used for #3369/#5527)|no|fix(opencode): expand retryable error patterns|
|40800|2026-08-06|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(opencode): serialize orphaned compaction history|
|40990|2026-08-07|loop|always-on|any existing task (make-it-run)|no|fix(opencode): order legacy message loop by time|
|41581|2026-08-10|prompt|always-on|any existing task (make-it-run)|no|fix(session): route all Muse family models to the Meta system prompt|
|41939|2026-08-11|loop|conditional|make-it-run + proxy fault injection (method used for #3369/#5527)|no|fix(opencode): cap session retries with jitter|
|42045|2026-08-12|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(compaction): adjust instructions and structure to be more clear to smaller models like dsv4 flash|
|43657|2026-08-20|subagent/agent|conditional|trig-subagent-resume|no|fix(opencode): surface resumable subagent errors|
|43821|2026-08-21|subagent/agent|conditional|trig-subagent-resume|no|fix(opencode): surface subagent tool errors|
|43813|2026-08-21|loop|conditional|make-it-run + proxy fault injection (method used for #3369/#5527)|no|fix(opencode): retry raw network finish errors|
|44633|2026-08-24|loop|conditional|make-it-run + proxy fault injection (method used for #3369/#5527)|no|fix(console): discontinue first-month Go discount|
|46653|2026-09-01|loop|always-on|any existing task (make-it-run)|no|feat(opencode): tolerate Anthropic thinking block binding|
|46820|2026-09-02|provider-format|always-on|any existing task (Anthropic path)|no|fix(opencode): let config opt out of Anthropic thinking blockBinding|
|46848|2026-09-02|provider-format|always-on|any existing task (Anthropic path)|no|fix(provider): scope thinking binding to Claude 5.1+|
|48057|2026-09-08|prompt|always-on|any existing task (make-it-run)|no|feat(opencode): port Astra system prompt from v2|
|50272|2026-09-20|session-other|conditional|make-it-run (path fires only on specific events; see diff)|no|fix(opencode): hoist Bedrock tool images except Claude, Nova, and Llama 4|
|53166|2026-10-12|tool|conditional|make-it-run; verify which tool|no|fix(core): preserve mixed line endings in edit tool|
|51062|2026-10-14|permission|needs-new-task|NEW trig-perm-ask: misleading-error copy whose fix needs `rm -rf build/` + edit outside cw|no|fix(mcp): pass tool input as permission metadata|
|55613|2026-10-15|context|conditional|taskflow with limit.context=72000 override (method used for #4838)|no|fix(core): fit compaction output limit to the request actually sent|