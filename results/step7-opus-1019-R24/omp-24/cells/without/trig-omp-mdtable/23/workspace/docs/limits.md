# API limits

Limits are per API key. Bursts above the limit get HTTP 429.

| Endpoint | Limit | Burst | Notes |
|---|---|---|---|
| `GET /items` | 600/min | 50 | cached at edge |
| `POST /items` | 60/min | 10 | idempotency key required |
| `GET /search` | 120/min | 20 | `q` max 256 chars \| no wildcards |
| `POST /export` | 5/hour | 1 | async; poll `/jobs` |

Contact support to raise a limit.
