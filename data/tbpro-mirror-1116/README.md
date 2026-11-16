# TB Pro base-image mirror attempt (2026-11-16)

**Result: not mirrored.** The Alibaba Cloud registry that 197 of 200 TB Pro
Dockerfiles build `FROM` is unreachable from GCP Asia as well as from the US.
Nothing was pushed to Artifact Registry.

## Source
- Upstream: `alibaba/terminal-bench-pro` @ `82bc46de337f48d57a5d78f4900ce7eabc485101`
  (the pin used by `obench/taskimport` on `sea-106/import-pipeline`, PR #264).
- All 201 Dockerfiles under `*/environment/` were read from git objects (no checkout)
  and their `FROM` lines are in `task-froms.csv`. That is 200 tasks plus one extra:
  `fix-docker-python-dependency-conflicts` has a second Dockerfile at
  `environment/docker/Dockerfile`, which is task content (the broken Dockerfile the agent
  must fix), not a second build environment. Its `FROM` row is listed too, so
  `task-froms.csv` has two rows for that task; the task counts below count it once.

## Distinct base images (`mapping.csv` / `mapping.json`)
| Base ref | Tasks | Pinned in Dockerfile |
|---|---|---|
| `skylensage-registry.cn-hangzhou.cr.aliyuncs.com/instances/1124:t-bench-python-3-13` | 129 | tag only |
| `skylensage-registry.cn-hangzhou.cr.aliyuncs.com/instances/1124:t-bench-ubuntu-24-04` | 68 (one, `setup-ubuntu-vm-ssh-key-auth`, uses it twice, as an `AS downloader` stage too) | tag only |
| `python:3.11-slim` (Docker Hub) | 2 | tag only |
| `python:3.13-slim` (Docker Hub) | 1 | tag only |

**No TB Pro Dockerfile pins its base by digest.** So there is no upstream pinned
digest to match. Any future mirror can only record "tag-only, resolved <date>".
The Docker Hub index digests in `mapping.json` were resolved on 2026-11-16 for the record.
They are reachable directly and were not mirrored.

## How the reachability test was run
- VM `thesis-mirror-asia` (e2-standard-4, asia-east1-b, Taiwan), plus one retry VM
  `thesis-mirror-asia-hk` (e2-small, asia-east2-a, Hong Kong). The org policy forbids
  external IPs, so both used Cloud NAT. Tooling: `crane` 0.20.2.
- From both regions, Docker Hub, GHCR and `registry.cn-hangzhou.aliyuncs.com` (the
  public ACR personal registry) answered. `skylensage-registry.cn-hangzhou.cr.aliyuncs.com`
  resolves to `120.26.27.123`, and TCP 443 and 80 to it time out
  (`crane digest` -> `dial tcp 120.26.27.123:443: i/o timeout`, 3 tries from HK).
  This looks like an ACR Enterprise instance whose public endpoint has an IP allowlist,
  not a geographic block.
- Both VMs were stopped (not deleted) after the test.

## Using this mapping
If a mirror is made later (for example, if upstream publishes the images elsewhere),
the rebuilt tasks should replace each `FROM <original_ref>` with the mirrored ref
pinned `@sha256:<mirrored_digest>`. Use only rows with `digest_match = true`
(mirrored digest == upstream digest, byte-exact copy with `crane copy`).
For now no row qualifies, so TB Pro stays out of the hard pool.
