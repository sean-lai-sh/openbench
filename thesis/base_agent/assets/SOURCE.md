# Vendored harness text

Prompt and tool-description text that the Pi and OpenCode configs send. Both
upstreams are MIT-licensed. Each directory keeps its upstream `LICENSE`.

## opencode/ (sst/opencode @ c10134729dd2ce00beb18604ec91f10319f59a78)

This is the sheet's OpenCode pin (`prereg/harness-components-2026-10-24.md`).
Files are copied byte for byte from `packages/opencode/src/`:

| File here | Upstream path |
|---|---|
| `anthropic.txt` | `session/prompt/anthropic.txt` |
| `title.txt` | `agent/prompt/title.txt` |
| `explore.txt` | `agent/prompt/explore.txt` |
| `tool-<name>.txt` | `tool/<name>.txt` (read, glob, grep, edit, write, task, webfetch, todowrite, skill, question) |
| `tool-shell.txt` | `tool/shell/shell.txt` (a template; `harness_opencode.py` fills it the way `tool/shell/prompt.ts` does) |
| `tool-shell-command.txt` | the `bashCommandSection` template literal in `tool/shell/prompt.ts`, with `` \` `` unescaped and `${limits.maxLines}` / `${limits.maxBytes}` renamed `${maxLines}` / `${maxBytes}` |

## pi/ (badlogic/pi-mono @ d0aa218cb16c333c008f6aa3dcd670ac8b68383c)

Pi builds its prompt and tool descriptions in TypeScript, not in text files.
The strings live in `harness_pi.py`, copied from
`packages/coding-agent/src/core/system-prompt.ts` and `core/tools/{read,bash,edit,write}.ts`.
This directory holds only Pi's `LICENSE`.

No Claude Code text is used anywhere.
