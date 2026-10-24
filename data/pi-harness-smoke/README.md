# Pi harness-comparison smoke

One local cell per model (`claude-opus-5-5`, `claude-sonnet-5-5`) on
`polyglot-rust-c`, through the Vertex proxy from PR #128. Pi is pinned to
`d0aa218cb16c333c008f6aa3dcd670ac8b68383c` and speaks Anthropic
`POST /v1/messages` (`models.json` `baseUrl` is the cell proxy without `/v1`).
The script builds that git commit. It does not install npm
`@earendil-works/pi-coding-agent@1.4.0` (tag `v1.4.0` is `4a080252`, a
different commit).

```bash
bash data/pi-harness-smoke/cell.sh /h2/pi-harness-smoke
```

Requires `GOOGLE_CLOUD_PROJECT` (or `GCLOUD_PROJECT`) and Application Default
Credentials. The script unsets `OBENCH_PI_VERTEX` so the A/B adapter path
does not run. Cell cap is 2400s. Transcripts stay under the output directory.

Each `<model>.json` holds the `run_cell` row (checker exit included), the
settings sidecar, proxy `totals.json` parsed into `all` / `main` / `side`,
and list-price cost for the all-call and main-only buckets. Smoke outcomes
are not analysed.
