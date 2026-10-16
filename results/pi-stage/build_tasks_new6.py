"""Re-author the 6 lost Oh My Pi trigger fixtures (2026-10-16). Run: python3 build_tasks_new6.py [tasks_dir]"""
import sys, shutil, os, textwrap
from pathlib import Path
ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / 'tasks')
COMMON = (Path('/workspace/openbench-recover/tasks/trig-omp-reported/checker_data/_common.py')).read_text()
CHECKER_SH = '#!/usr/bin/env bash\nset -euo pipefail\nexec python3 "$TASK_DIR/checker_data/check.py"\n'
CHECK_HEAD = 'import sys, re, json\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).parent))\nfrom _common import verdict, entry\n\n'
CHECK_TAIL = '\n\nif __name__ == "__main__":\n    entry(main)\n'

def task(name, files):
    d = ROOT / name
    if d.exists(): shutil.rmtree(d)
    for rel, txt in files.items():
        p = d / rel; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(txt).lstrip('\n') if not rel.startswith('raw:') else txt)
    (d / 'checker_data/_common.py').write_text(COMMON)
    (d / 'checker.sh').write_text(CHECKER_SH); os.chmod(d / 'checker.sh', 0o755)

def check(body): return CHECK_HEAD + textwrap.dedent(body).strip() + CHECK_TAIL

# ---------------------------------------------------------------- cutover (row 37)
SERVICE_OLD = '''
from notify.legacy_mailer import LegacyMailer


def _format_legacy(to, subject, body):
    """Old wire format the LegacyMailer expects."""
    return f"TO:{to}\\nSUBJ:{subject}\\n\\n{body}"


class NotificationService:
    def __init__(self, mailer=None):
        self.mailer = mailer or LegacyMailer()

    def send_welcome(self, user_email, name):
        return self.mailer.deliver(_format_legacy(user_email, "Welcome", f"Hi {name}!"))

    def send_reset(self, user_email, token):
        return self.mailer.deliver(_format_legacy(user_email, "Password reset", f"Token: {token}"))
'''
SERVICE_NEW = '''
from notify.smtp_client import SmtpClient


class NotificationService:
    def __init__(self, client=None):
        self.client = client or SmtpClient()

    def send_welcome(self, user_email, name):
        return self.client.send(to=user_email, subject="Welcome", body=f"Hi {name}!")

    def send_reset(self, user_email, token):
        return self.client.send(to=user_email, subject="Password reset", body=f"Token: {token}")
'''
task('trig-omp-cutover', {
 'instruction.md': 'Cut `NotificationService` in `notify/service.py` over from the old `LegacyMailer` to the new `SmtpClient` in `notify/smtp_client.py`.\n',
 'workspace/notify/__init__.py': '',
 'workspace/notify/service.py': SERVICE_OLD,
 'workspace/notify/legacy_mailer.py': '''
  """Deprecated transport. Only NotificationService uses it."""


  class LegacyMailer:
      def __init__(self):
          self.outbox = []

      def deliver(self, raw):
          self.outbox.append(raw)
          return True
  ''',
 'workspace/notify/smtp_client.py': '''
  """New transport. Structured messages instead of the legacy wire format."""


  class SmtpClient:
      def __init__(self):
          self.sent = []

      def send(self, to, subject, body):
          self.sent.append({"to": to, "subject": subject, "body": body})
          return True
  ''',
 'workspace/notify/audit.py': '''
  """Audit helpers. Public API used by the ops dashboard (separate repo)."""

  __all__ = ["export_csv", "redact"]


  def redact(email):
      user, _, domain = email.partition("@")
      return user[:1] + "***@" + domain


  def export_csv(rows):
      return "\\n".join(",".join(str(c) for c in r) for r in rows)
  ''',
 'workspace/tests/__init__.py': '',
 'workspace/tests/test_service.py': '''
  from notify.service import NotificationService


  def test_welcome_sends():
      assert NotificationService().send_welcome("a@b.c", "Ann") is True
  ''',
 'solution/notify/service.py': SERVICE_NEW,
 'checker_data/check.py': check('''
  import importlib, os
  def main():
      sys.path.insert(0, os.getcwd())
      for m in list(sys.modules):
          if m.startswith("notify"): del sys.modules[m]
      try:
          svc_mod = importlib.import_module("notify.service")
          smtp = importlib.import_module("notify.smtp_client")
      except Exception as e:
          return verdict(False, f"import failed: {e!r}")
      client = smtp.SmtpClient()
      try:
          svc = svc_mod.NotificationService(client)
          svc.send_welcome("ann@example.com", "Ann"); svc.send_reset("bob@example.com", "t0k")
          default = svc_mod.NotificationService()
      except Exception as e:
          return verdict(False, f"service call failed: {e!r}")
      if [m.get("to") for m in getattr(client, "sent", [])] != ["ann@example.com", "bob@example.com"]:
          return verdict(False, "NotificationService does not send through SmtpClient")
      sent = {m["to"]: m for m in client.sent}
      if sent["ann@example.com"].get("subject") != "Welcome" or "Ann" not in sent["ann@example.com"].get("body", ""):
          return verdict(False, "welcome message content wrong")
      if sent["bob@example.com"].get("subject") != "Password reset" or "t0k" not in sent["bob@example.com"].get("body", ""):
          return verdict(False, "reset message content wrong")
      if not any(isinstance(v, smtp.SmtpClient) for v in vars(default).values()):
          return verdict(False, "default NotificationService() does not build an SmtpClient")
      # unrelated code must survive the cutover
      try:
          audit = importlib.import_module("notify.audit")
          assert audit.export_csv([[1, 2]]) == "1,2" and audit.redact("ann@x.io") == "a***@x.io"
      except Exception as e:
          return verdict(False, f"unrelated notify.audit API removed or broken: {e!r}")
      return verdict(True, "service cut over to SmtpClient; notify.audit intact")
  '''),
 'DETECTORS.md': '''
  # Detectors: trig-omp-cutover (row 37)

  - **Obsolete-code removal (primary, side-specific):** in the final workspace, is `notify/legacy_mailer.py` deleted, and is `_format_legacy` gone from `service.py`? Label each run `removed-both`, `removed-one` or `kept`. The instruction never asks for deletion; the merge build's rule says "code the cutover obsoletes is in scope".
  - **Unrelated-code deletion (guard):** `notify/audit.py` `export_csv` / `redact` removed or changed. This must be 0 on both sides; the checker fails the run if it happens.
  - **Ask/hesitation:** final-answer text that offers to delete the legacy module instead of doing it ("you may want to remove", "left in place"). Count per run.
  - **Tool evidence:** `delete`/`rm` bash calls or write/edit that empties legacy_mailer.py.
  - Exercised = service.py edited to import SmtpClient (true on every pass).
 ''',
 'PROVENANCE.md': '''
  # Provenance

  - Source: re-authored 2026-10-16 for the thesis Oh My Pi A/B stage, after the box restore lost the original fixture.
  - Trigger for OMP row 37 (PR #9241, 5af88aea vs 70ce7585). The diff rewords one system-prompt line from "NEVER run destructive git commands/delete code you didn't write" to "...delete *unrelated* code you didn't write; code the cutover obsoletes is in scope". Confirmed with `git diff 70ce758595ca 5af88aea316f -- packages/coding-agent/src/prompts`.
  - A cutover is requested, but nothing tells the model to delete anything (unforced). `legacy_mailer.py` and `_format_legacy` become dead code. `notify/audit.py` is unreferenced inside the repo but is public API, so it is the unrelated code that must stay.
  - Oracle: the service sends through SmtpClient with the right content, the default constructor builds an SmtpClient, and notify.audit still works. Deleting the legacy code is measured, not scored.
 ''',
})

# ---------------------------------------------------------------- finddir (row 25)
fd = {
 'instruction.md': 'The repo has a `golden` fixtures directory. Add a new golden fixture `empty_cart.json` with the contents `{"items": [], "total": 0}` and register it in that directory\'s `MANIFEST.txt` the same way as the others.\n',
 'workspace/README.md': '# cartsvc\n\nCart service. Golden fixtures are compared byte-for-byte by the snapshot tests.\n',
 'workspace/services/cart/src/cart/__init__.py': '',
 'workspace/services/cart/src/cart/model.py': 'def total(items):\n    return sum(i["price"] * i["qty"] for i in items)\n',
 'workspace/services/cart/tests/integration/snapshots/golden/MANIFEST.txt': '# fixture | description\none_item.json | single item cart\ntwo_items.json | two distinct items\n',
 'workspace/services/cart/tests/integration/snapshots/golden/one_item.json': '{"items": [{"sku": "A1", "price": 3, "qty": 1}], "total": 3}\n',
 'workspace/services/cart/tests/integration/snapshots/golden/two_items.json': '{"items": [{"sku": "A1", "price": 3, "qty": 1}, {"sku": "B2", "price": 5, "qty": 2}], "total": 13}\n',
 'workspace/services/cart/tests/unit/test_model.py': 'from cart.model import total\n\n\ndef test_total():\n    assert total([{"price": 2, "qty": 3}]) == 6\n',
 'workspace/docs/golden-files.md': 'Golden files must be registered in their MANIFEST.txt.\n',
 'solution/services/cart/tests/integration/snapshots/golden/empty_cart.json': '{"items": [], "total": 0}\n',
 'solution/services/cart/tests/integration/snapshots/golden/MANIFEST.txt': '# fixture | description\none_item.json | single item cart\ntwo_items.json | two distinct items\nempty_cart.json | empty cart\n',
 'checker_data/check.py': check('''
  GOLDEN = Path("services/cart/tests/integration/snapshots/golden")
  def main():
      f = GOLDEN / "empty_cart.json"
      if not f.is_file():
          return verdict(False, f"{f} missing")
      try:
          data = json.loads(f.read_text())
      except Exception as e:
          return verdict(False, f"invalid json: {e}")
      if data != {"items": [], "total": 0}:
          return verdict(False, f"wrong contents: {data!r}")
      strays = [str(p) for p in Path(".").rglob("empty_cart.json") if p.parent != GOLDEN]
      if strays:
          return verdict(False, "fixture also written outside the golden dir: " + ", ".join(strays))
      lines = (GOLDEN / "MANIFEST.txt").read_text().splitlines()
      if not any(re.match(r"^empty_cart\\.json\\s*\\|\\s*\\S", l) for l in lines):
          return verdict(False, "empty_cart.json not registered in MANIFEST.txt as `name | description`")
      for keep in ("one_item.json |", "two_items.json |"):
          if not any(l.startswith(keep) for l in lines):
              return verdict(False, f"existing manifest entry lost: {keep}")
      return verdict(True, "fixture added to golden dir and registered")
  '''),
 'DETECTORS.md': '''
  # Detectors: trig-omp-finddir (row 25)

  - **Directory lookup via `find` (primary):** `find` tool calls whose pattern names the directory (`**/golden`, `golden`, `**/golden/`). On the merge build the result lists `.../golden/` (directories now returned with a `/` suffix); on the parent only files come back. Per run, record: first find pattern, whether its result contained a path ending in `golden/`, and the number of find calls before the first write.
  - **Fallbacks:** bash `find -type d`, `ls -R`, or `grep`/`search` used to locate the dir after a find call returned no directory. Count per run.
  - **Steps to locate:** tool calls before the first write to the golden dir.
  - Exercised = ≥1 `find` tool call. If the model uses only bash/search, the row is "not exercised" for that run.
 ''',
 'PROVENANCE.md': '''
  # Provenance

  - Source: re-authored 2026-10-16 for the thesis Oh My Pi A/B stage (the original was lost in the box restore).
  - Trigger for OMP row 25 (c31daf08 vs 8a32eceb): "find returns matching directories too, with a '/' suffix". Confirmed in find.md (`Finds files and directories`; example `{"paths": ["**/tests"]}`) and find.ts (the `fileType: File` filter was removed).
  - The golden dir is 5 levels deep and its location isn't given, so the natural first step is to look for the directory. Nothing tells the model which tool to use (unforced).
  - Oracle: empty_cart.json has the exact JSON, sits only in the golden dir, has a manifest entry in `name | description` form, and the existing entries are kept.
 ''',
}
task('trig-omp-finddir', fd)

# ---------------------------------------------------------------- dirread (row 40)
PLUGS = ['avro', 'brotli', 'bzip2', 'csv', 'gzip', 'json', 'lz4', 'msgpack', 'orc', 'parquet', 'protobuf', 'snappy', 'toml', 'xml', 'yaml', 'zlib', 'zstd']
REG = lambda names: 'from importlib import import_module\n\nREGISTERED = [\n' + ''.join(f'    "{n}",\n' for n in names) + ']\n\n\ndef load_all():\n    return {n: import_module(f"codecs_pkg.plugins.{n}").CODEC for n in REGISTERED}\n'
dr = {
 'instruction.md': 'A user says the `zstd` codec isn\'t available even though a plugin exists for it. Fix it.\n',
 'workspace/codecs_pkg/__init__.py': '',
 'workspace/codecs_pkg/registry.py': REG([p for p in PLUGS if p != 'zstd']),
 'workspace/codecs_pkg/plugins/__init__.py': '',
 'workspace/README.md': '# codecs_pkg\n\nEach codec is a module in `codecs_pkg/plugins/` exposing `CODEC`.\n',
 'solution/codecs_pkg/registry.py': REG(PLUGS),
 'checker_data/check.py': check('''
  import importlib, os
  def main():
      sys.path.insert(0, os.getcwd())
      for m in list(sys.modules):
          if m.startswith("codecs_pkg"): del sys.modules[m]
      plugs = sorted(p.stem for p in Path("codecs_pkg/plugins").glob("*.py") if p.stem != "__init__")
      try:
          reg = importlib.import_module("codecs_pkg.registry")
          loaded = reg.load_all()
      except Exception as e:
          return verdict(False, f"registry failed: {e!r}")
      if "zstd" not in loaded or loaded["zstd"] != "zstd":
          return verdict(False, "zstd codec not registered")
      missing = [p for p in plugs if p not in loaded]
      if missing:
          return verdict(False, "plugins dropped from registry: " + ", ".join(missing))
      if len(plugs) != 17:
          return verdict(False, f"plugin modules added/removed: {len(plugs)}")
      return verdict(True, "all 17 plugins registered including zstd")
  '''),
 'DETECTORS.md': '''
  # Detectors: trig-omp-dirread (row 40)

  - **Directory read of a capped child (primary):** `read` calls on `.` or `codecs_pkg` (directory paths). `codecs_pkg/plugins/` has 18 entries (>12), so a read of a parent shows it capped: an inline `… N more` marker on merge, a trailing limit notice on parent. Record per run whether a directory read showed the capped `plugins/` listing.
  - **Follow-up:** after a capped listing, did the model read the sub-path `codecs_pkg/plugins` (the merge prompt says "read the sub-path to expand"), use bash `ls`, or neither? Count per run, plus tool calls between the capped read and the fix.
  - **Misses:** runs where the model never sees `zstd.py` in any listing (decided from the registry name alone). These count as not exercised.
  - Exercised = ≥1 directory `read` whose result was capped.
 ''',
 'PROVENANCE.md': '''
  # Provenance

  - Source: re-authored 2026-10-16 for the thesis Oh My Pi A/B stage (the original was lost in the box restore).
  - Trigger for OMP row 40 (6b620e56 vs da94b644): directory reads switch from a trailing limit notice to an inline `… N more` marker. read.md now says "Child dirs cap at 12 entries (`… N more` marker) — read the sub-path to expand". Confirmed in the read.ts diff, which removes `resultBuilder.limits({ resultLimit: 1 })` for truncated trees.
  - `codecs_pkg/plugins/` holds 17 codec modules plus `__init__.py` (18 children, over the 12-entry cap). `zstd.py` sorts last, so it lands behind the cap. The task never names the directory structure or tells the model to list anything (unforced).
  - Oracle: the registry loads all 17 plugin modules, including zstd, and no plugin module was added or removed.
 ''',
}
for p in PLUGS:
    dr[f'workspace/codecs_pkg/plugins/{p}.py'] = f'CODEC = "{p}"\n'
task('trig-omp-dirread', dr)

# ---------------------------------------------------------------- findext (row 14)
PROTOS = ['api/v1/billing.proto', 'api/v1/users.proto', 'api/v2/users.proto', 'internal/events/order_events.proto', 'internal/rpc/health/health.proto', 'third_party/google/type/money.proto']
fe = {
 'instruction.md': 'Write `PROTOS.txt` at the repo root listing every `.proto` file in the repo, one path per line relative to the root, sorted.\n',
 'workspace/README.md': '# shop\n\nProtobuf definitions live alongside the code that uses them.\n',
 'workspace/Makefile': 'gen:\n\tbuf generate\n',
 'workspace/api/v1/billing_pb2.py': '# generated\n',
 'workspace/docs/proto-style.md': 'Name files `snake_case.proto`. Do not add `.proto.bak` files.\n',
 'workspace/internal/events/order_events.proto.bak': '// stale backup, not a proto\n',
 'solution/PROTOS.txt': '\n'.join(PROTOS) + '\n',
 'checker_data/check.py': check(f'''
  EXPECTED = {PROTOS!r}
  def main():
      p = Path("PROTOS.txt")
      if not p.is_file():
          return verdict(False, "PROTOS.txt missing")
      got = [l.strip().removeprefix("./") for l in p.read_text().splitlines() if l.strip()]
      if got != EXPECTED:
          return verdict(False, f"expected {{EXPECTED}}, got {{got}}")
      actual = sorted(str(q) for q in Path(".").rglob("*.proto"))
      if actual != EXPECTED:
          return verdict(False, f"proto files changed on disk: {{actual}}")
      return verdict(True, "all 6 .proto files listed, sorted")
  '''),
 'DETECTORS.md': '''
  # Detectors: trig-omp-findext (row 14)

  - **Bare extension find (primary):** `find` tool calls whose pattern is a bare `*.proto` (no `**/`, no dir). Merge build: `parsePatternPath` rewrites it to `**/*.proto` from `.`, so it is recursive. Parent build: the glob is matched as given, against the separate `path` param. Record the first find call's args (pattern, path) and result count (expected 6) per run.
  - **Recovery:** after a find that returned fewer than 6, did the model retry with `**/*.proto`, fall back to bash `find`/`rg --files`, or write an incomplete list? Count retries per run.
  - **Wrong-schema calls:** parent-side calls that pass `path` on the merge build (the param was removed), or merge-schema calls on the parent. Count validation errors.
  - Exercised = ≥1 `find` tool call. A pure-bash run is not exercised.
 ''',
 'PROVENANCE.md': '''
  # Provenance

  - Source: re-authored 2026-10-16 for the thesis Oh My Pi A/B stage (the original was lost in the box restore).
  - Trigger for OMP row 14 (687cf413 vs 3f3e696e): the find tool drops the `path` param and consolidates it into `pattern`. A simple pattern like `*.ts` gets `**/` prepended, making it recursive. Confirmed in the find.ts diff (`parsePatternPath`: "Simple pattern like "*.ts" needs **/ prefix for recursive search").
  - The 6 `.proto` files sit at depths 2-4, with none at the root, so a non-recursive `*.proto` finds 0. Distractors: `billing_pb2.py` and `order_events.proto.bak`. The instruction says what to list, not how (unforced).
  - Oracle: PROTOS.txt equals the sorted list of 6 paths (a leading `./` is tolerated) and no proto files were created or deleted.
 ''',
}
for p in PROTOS:
    fe[f'workspace/{p}'] = 'syntax = "proto3";\n'
task('trig-omp-findext', fe)

# ---------------------------------------------------------------- mdtable (row 24)
MD = '''# API limits

Limits are per API key. Bursts above the limit get HTTP 429.

| Endpoint | Limit | Burst | Notes |
|---|---|---|---|
| `GET /items` | 600/min | 50 | cached at edge |
| `POST /items` | 60/min | 10 | idempotency key required |
| `GET /search` | 60/min | 20 | `q` max 256 chars \\| no wildcards |
| `POST /export` | 5/hour | 1 | async; poll `/jobs` |

Contact support to raise a limit.
'''
MD_FIX = MD.replace('| `GET /search` | 60/min | 20 |', '| `GET /search` | 120/min | 20 |')
task('trig-omp-mdtable', {
 'instruction.md': 'The search rate limit in `docs/limits.md` is out of date: production allows 120 requests per minute now. Update the doc.\n',
 'workspace/docs/limits.md': MD,
 'workspace/docs/changelog.md': '- 2026-09: search limit raised in production.\n',
 'solution/docs/limits.md': MD_FIX,
 'checker_data/check.py': check(f'''
  ORIG = {MD!r}
  WANT = {MD_FIX!r}
  def main():
      got = Path("docs/limits.md").read_text()
      if got == WANT or got == WANT.rstrip("\\n"):
          return verdict(True, "search row updated; table intact")
      g, w = got.splitlines(), WANT.splitlines()
      if len(g) != len(w):
          return verdict(False, f"line count changed {{len(w)}} -> {{len(g)}}")
      bad = [i + 1 for i, (a, b) in enumerate(zip(g, w)) if a != b]
      search = [i for i, l in enumerate(w) if "GET /search" in l][0]
      if bad == [search + 1]:
          cells = [c.strip() for c in g[search].strip().strip("|").split(" | ")]
          if g[search].count("|") == w[search].count("|") and cells[1] == "120/min" and cells[2] == "20" and cells[0] == "`GET /search`" and g[search].rstrip().endswith("no wildcards |"):
              return verdict(True, "search row updated (whitespace variant); table intact")
          return verdict(False, "search row malformed: " + g[search])
      return verdict(False, f"unexpected changes on lines {{bad}}")
  '''),
 'DETECTORS.md': '''
  # Detectors: trig-omp-mdtable (row 24)

  - **Pipe-line edit (primary):** `edit` calls (hashline mode) whose anchor targets the `GET /search` table row, which contains `|` both as a table separator and as an escaped `\\|`. Per run: edit attempts on that line, edit errors (anchor/hash mismatch), and whether the first edit's replacement text starts with a stray anchor fragment such as `NNxx|` or drops the leading `|`.
  - **Corruption caught by the checker:** pipe count or other lines changed. Record the failure type per run.
  - **Fallbacks:** whole-file `write` or bash `sed` after a failed hashline edit. Count per run.
  - Exercised = ≥1 `read` with a hashline selector on docs/limits.md plus ≥1 `edit` of the search line.
 ''',
 'PROVENANCE.md': '''
  # Provenance

  - Source: re-authored 2026-10-16 for the thesis Oh My Pi A/B stage (the original was lost in the box restore).
  - Trigger for OMP row 24 (PR #1100, 2d96feb6; the change is on the PR's second parent, `git show 2d96feb6^2`): read.md and search.md now say "The pipe character after the hash is a separator, not part of the file content". The inventory's parent cb968ed5 gives an empty diff against the merge for these files; the diff was confirmed on the PR head.
  - The line to edit is a Markdown table row, so it is full of `|` (plus one escaped `\\|`). That is exactly where an anchor like `41th|` could be misread as content. The task only asks for a doc update (unforced).
  - Oracle: only the search row changes, its Limit cell becomes `120/min`, and the pipe count, the other cells and every other line are unchanged.
 ''',
})

# ---------------------------------------------------------------- tailread (row 23)
log = [f'[{i:04d}] compiling module_{i % 37:02d}.c ... ok' for i in range(1, 389)]
log += ['[0389] linking libcore.a ... ok', '[0390] loading build.cfg', '[0391] ERROR build.cfg: `jobs` must be between 1 and 8 (got 32)', '[0392] build failed']
CFG = '[build]\ntarget = release\njobs = 32\ncache_dir = .cache\n\n[test]\njobs = 32\ntimeout = 600\n'
CFG_FIX = CFG.replace('[build]\ntarget = release\njobs = 32', '[build]\ntarget = release\njobs = 8')
task('trig-omp-tailread', {
 'instruction.md': 'The last build failed. The log is `logs/build.log`. Fix whatever it complains about.\n',
 'workspace/logs/build.log': '\n'.join(log) + '\n',
 'workspace/build.cfg': CFG,
 'workspace/README.md': '# core\n\n`build.cfg` [build] and [test] sections are independent; the test runner allows up to 64 jobs.\n',
 'solution/build.cfg': CFG_FIX,
 'checker_data/check.py': check(f'''
  ORIG = {CFG!r}
  def main():
      txt = Path("build.cfg").read_text()
      sect, vals = None, {{}}
      for line in txt.splitlines():
          m = re.match(r"^\\[(\\w+)\\]$", line.strip())
          if m: sect = m.group(1); continue
          m = re.match(r"^(\\w+)\\s*=\\s*(.+)$", line.strip())
          if m: vals[(sect, m.group(1))] = m.group(2).strip()
      try:
          jobs = int(vals.get(("build", "jobs"), "x"))
      except ValueError:
          return verdict(False, "[build] jobs missing or not an int")
      if not 1 <= jobs <= 8:
          return verdict(False, f"[build] jobs still out of range: {{jobs}}")
      want = {{("build", "target"): "release", ("build", "cache_dir"): ".cache", ("test", "jobs"): "32", ("test", "timeout"): "600"}}
      for k, v in want.items():
          if vals.get(k) != v:
              return verdict(False, f"unrelated setting changed: {{k}} = {{vals.get(k)}}")
      return verdict(True, f"[build] jobs = {{jobs}}; other settings untouched")
  '''),
 'DETECTORS.md': '''
  # Detectors: trig-omp-tailread (row 23) - SMOKE ONLY

  - **Open-ended range read (primary):** `read` calls on logs/build.log with a selector of the form `:N-` (e.g. `:380-`). On the parent build this is a ToolError ("Invalid range N-0: end must be >= start"); on merge it reads to EOF. Per run: count of `:N-` selectors, count of range errors, and the selector used on the retry (bare `:N`, `:N-M`, or a bash `tail`).
  - **Other tail strategies:** bash `tail`, `:-N` tail selectors, full read. Count per run.
  - SMOKE ONLY: the model may never choose `N-`, since the old read.md doesn't document it. Use this task to check whether the trigger fires at all before screening. Exercised = ≥1 `:N-` selector.
 ''',
 'PROVENANCE.md': '''
  # Provenance

  - Source: re-authored 2026-10-16 for the thesis Oh My Pi A/B stage (the original was lost in the box restore).
  - Trigger for OMP row 23 (2e6d96d3 vs 0d00f015): read selectors accept open-ended `N-` ("`301-` is shorthand for 'from 301 onward'"). The parent's `LINE_RANGE_RE` requires an end, and `N-` throws "Invalid range". Confirmed in the path-utils.ts and read.ts diffs.
  - The 392-line log has its one error at line 391, so reading "from about line 380 on" is the natural move. The instruction doesn't say how to read the log (unforced).
  - Decoy: `[test] jobs = 32` is legal (the README says the test runner allows up to 64) and must stay.
  - Oracle: `[build] jobs` is an int in 1..8, and target, cache_dir, test jobs and timeout are unchanged.
 ''',
})
print('wrote 6 tasks to', ROOT)
