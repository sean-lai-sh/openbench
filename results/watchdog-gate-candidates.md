# Watchdog gate candidates

The 52 `data/h2-deferred-1023` hangs whose saved `output_tail` contains a timestamped `message.part.updated`. Gap is seconds from that last stamp (UTC, whole seconds) to the kill (`started_at` + `t_agent_s`), shown to 0.1s. Sorted ascending.

**Fixed rule:** relabel only if the gap is **<= 290s**. Every gap in this table is between 297.1s and 300.6s, so all 52 stay hang. They are not relabeled and they are not in the rerun set. opus/13331 without regex-chess trial 7 also stays hang.

| gap_s | verdict | model | pr | side | task | trial | last message.part.updated (UTC) | kill (UTC) | idle_s | cell |
| ---: | --- | --- | --- | --- | --- | ---: | --- | --- | ---: | --- |
| 297.1 | stays_hang | opus | 13331 | without | regex-chess | 6 | 2026-10-24T02:44:00 | 2026-10-24T02:48:57.050804 | 300.0 | `opus/13331/cells/without/regex-chess/6.json` |
| 297.8 | stays_hang | opus | 13090 | without | regex-chess | 1 | 2026-10-23T22:16:18 | 2026-10-23T22:21:15.833504 | 300.2 | `opus/13090/cells/without/regex-chess/1.json` |
| 298.1 | stays_hang | opus | 13090 | with | regex-chess | 7 | 2026-10-24T00:07:56 | 2026-10-24T00:12:54.099522 | 300.1 | `opus/13090/cells/with/regex-chess/7.json` |
| 298.4 | stays_hang | opus | 13331 | with | regex-chess | 6 | 2026-10-24T02:42:22 | 2026-10-24T02:47:20.409680 | 300.1 | `opus/13331/cells/with/regex-chess/6.json` |
| 298.5 | stays_hang | opus | 13090 | without | regex-chess | 7 | 2026-10-24T00:06:20 | 2026-10-24T00:11:18.456194 | 300.2 | `opus/13090/cells/without/regex-chess/7.json` |
| 298.6 | stays_hang | opus | 26821 | with | regex-chess | 4 | 2026-10-24T05:11:54 | 2026-10-24T05:16:52.560351 | 300.0 | `opus/26821/cells/with/regex-chess/4.json` |
| 298.6 | stays_hang | opus | 13090 | with | regex-chess | 1 | 2026-10-23T22:20:41 | 2026-10-23T22:25:39.593487 | 300.3 | `opus/13090/cells/with/regex-chess/1.json` |
| 298.7 | stays_hang | opus | 13331 | with | regex-chess | 4 | 2026-10-24T02:06:12 | 2026-10-24T02:11:10.706521 | 300.1 | `opus/13331/cells/with/regex-chess/4.json` |
| 298.7 | stays_hang | opus | 26821 | with | regex-chess | 2 | 2026-10-24T04:39:56 | 2026-10-24T04:44:54.720520 | 300.0 | `opus/26821/cells/with/regex-chess/2.json` |
| 298.9 | stays_hang | opus | 13331 | with | regex-chess | 9 | 2026-10-24T03:39:13 | 2026-10-24T03:44:11.897033 | 300.2 | `opus/13331/cells/with/regex-chess/9.json` |
| 299.0 | stays_hang | opus | 26821 | with | regex-chess | 3 | 2026-10-24T04:51:48 | 2026-10-24T04:56:46.952525 | 300.1 | `opus/26821/cells/with/regex-chess/3.json` |
| 299.0 | stays_hang | opus | 26821 | with | regex-chess | 1 | 2026-10-24T04:17:08 | 2026-10-24T04:22:07.030663 | 300.1 | `opus/26821/cells/with/regex-chess/1.json` |
| 299.1 | stays_hang | sonnet | 26821 | without | regex-chess | 5 | 2026-10-23T08:48:10 | 2026-10-23T08:53:09.062689 | 300.1 | `sonnet/26821/cells/without/regex-chess/5.json` |
| 299.1 | stays_hang | opus | 26821 | without | regex-chess | 4 | 2026-10-24T05:12:14 | 2026-10-24T05:17:13.103793 | 300.1 | `opus/26821/cells/without/regex-chess/4.json` |
| 299.1 | stays_hang | sonnet | 26821 | with | regex-chess | 5 | 2026-10-23T08:48:34 | 2026-10-23T08:53:33.109487 | 300.0 | `sonnet/26821/cells/with/regex-chess/5.json` |
| 299.1 | stays_hang | opus | 13331 | with | regex-chess | 10 | 2026-10-24T03:59:20 | 2026-10-24T04:04:19.135535 | 300.1 | `opus/13331/cells/with/regex-chess/10.json` |
| 299.1 | stays_hang | opus | 26821 | without | regex-chess | 1 | 2026-10-24T04:17:44 | 2026-10-24T04:22:43.148583 | 300.2 | `opus/26821/cells/without/regex-chess/1.json` |
| 299.2 | stays_hang | opus | 13331 | with | regex-chess | 7 | 2026-10-24T03:04:13 | 2026-10-24T03:09:12.161527 | 300.2 | `opus/13331/cells/with/regex-chess/7.json` |
| 299.2 | stays_hang | opus | 13090 | with | regex-chess | 9 | 2026-10-24T00:40:57 | 2026-10-24T00:45:56.170248 | 300.1 | `opus/13090/cells/with/regex-chess/9.json` |
| 299.3 | stays_hang | opus | 13090 | with | regex-chess | 10 | 2026-10-24T00:56:08 | 2026-10-24T01:01:07.254214 | 300.0 | `opus/13090/cells/with/regex-chess/10.json` |
| 299.3 | stays_hang | opus | 13331 | without | regex-chess | 4 | 2026-10-24T02:05:00 | 2026-10-24T02:09:59.302517 | 300.3 | `opus/13331/cells/without/regex-chess/4.json` |
| 299.4 | stays_hang | opus | 13331 | with | regex-chess | 5 | 2026-10-24T02:25:40 | 2026-10-24T02:30:39.408800 | 300.2 | `opus/13331/cells/with/regex-chess/5.json` |
| 299.4 | stays_hang | opus | 26821 | without | regex-chess | 3 | 2026-10-24T04:52:06 | 2026-10-24T04:57:05.425513 | 300.2 | `opus/26821/cells/without/regex-chess/3.json` |
| 299.5 | stays_hang | sonnet | 26821 | with | regex-chess | 1 | 2026-10-23T08:07:20 | 2026-10-23T08:12:19.465435 | 300.0 | `sonnet/26821/cells/with/regex-chess/1.json` |
| 299.5 | stays_hang | opus | 13331 | without | regex-chess | 9 | 2026-10-24T03:44:20 | 2026-10-24T03:49:19.465520 | 300.4 | `opus/13331/cells/without/regex-chess/9.json` |
| 299.5 | stays_hang | sonnet | 13331 | without | regex-chess | 4 | 2026-10-23T06:48:32 | 2026-10-23T06:53:31.485459 | 300.1 | `sonnet/13331/cells/without/regex-chess/4.json` |
| 299.5 | stays_hang | opus | 26821 | without | regex-chess | 2 | 2026-10-24T04:37:59 | 2026-10-24T04:42:58.498507 | 300.2 | `opus/26821/cells/without/regex-chess/2.json` |
| 299.6 | stays_hang | opus | 13090 | without | regex-chess | 2 | 2026-10-23T22:43:04 | 2026-10-23T22:48:03.638128 | 300.2 | `opus/13090/cells/without/regex-chess/2.json` |
| 299.7 | stays_hang | opus | 13090 | without | regex-chess | 5 | 2026-10-23T23:28:44 | 2026-10-23T23:33:43.659074 | 300.2 | `opus/13090/cells/without/regex-chess/5.json` |
| 299.7 | stays_hang | opus | 13090 | with | regex-chess | 6 | 2026-10-23T23:47:50 | 2026-10-23T23:52:49.665834 | 300.2 | `opus/13090/cells/with/regex-chess/6.json` |
| 299.7 | stays_hang | sonnet | 26821 | without | regex-chess | 3 | 2026-10-23T08:24:35 | 2026-10-23T08:29:34.673475 | 300.2 | `sonnet/26821/cells/without/regex-chess/3.json` |
| 299.7 | stays_hang | opus | 13331 | without | regex-chess | 1 | 2026-10-24T01:10:26 | 2026-10-24T01:15:25.712496 | 300.2 | `opus/13331/cells/without/regex-chess/1.json` |
| 299.7 | stays_hang | sonnet | 26821 | without | regex-chess | 4 | 2026-10-23T08:37:21 | 2026-10-23T08:42:20.720445 | 300.1 | `sonnet/26821/cells/without/regex-chess/4.json` |
| 299.8 | stays_hang | opus | 13090 | without | regex-chess | 6 | 2026-10-23T23:51:27 | 2026-10-23T23:56:26.784092 | 300.1 | `opus/13090/cells/without/regex-chess/6.json` |
| 299.8 | stays_hang | sonnet | 26821 | with | regex-chess | 9 | 2026-10-23T09:32:49 | 2026-10-23T09:37:48.802712 | 300.1 | `sonnet/26821/cells/with/regex-chess/9.json` |
| 299.8 | stays_hang | opus | 13331 | with | regex-chess | 3 | 2026-10-24T01:47:12 | 2026-10-24T01:52:11.808514 | 300.2 | `opus/13331/cells/with/regex-chess/3.json` |
| 299.8 | stays_hang | opus | 13331 | without | regex-chess | 2 | 2026-10-24T01:29:07 | 2026-10-24T01:34:06.814345 | 300.1 | `opus/13331/cells/without/regex-chess/2.json` |
| 299.8 | stays_hang | opus | 13090 | without | regex-chess | 3 | 2026-10-23T23:01:29 | 2026-10-23T23:06:28.814566 | 300.1 | `opus/13090/cells/without/regex-chess/3.json` |
| 299.9 | stays_hang | opus | 13331 | with | regex-chess | 8 | 2026-10-24T03:23:48 | 2026-10-24T03:28:47.863533 | 300.1 | `opus/13331/cells/with/regex-chess/8.json` |
| 299.9 | stays_hang | opus | 13090 | with | regex-chess | 3 | 2026-10-23T23:01:34 | 2026-10-23T23:06:33.878001 | 300.2 | `opus/13090/cells/with/regex-chess/3.json` |
| 299.9 | stays_hang | opus | 13331 | with | regex-chess | 1 | 2026-10-24T01:11:32 | 2026-10-24T01:16:31.878017 | 300.1 | `opus/13331/cells/with/regex-chess/1.json` |
| 300.0 | stays_hang | opus | 13090 | with | regex-chess | 8 | 2026-10-24T00:21:09 | 2026-10-24T00:26:09.021966 | 300.1 | `opus/13090/cells/with/regex-chess/8.json` |
| 300.1 | stays_hang | sonnet | 26821 | with | regex-chess | 2 | 2026-10-23T08:15:38 | 2026-10-23T08:20:38.113648 | 300.1 | `sonnet/26821/cells/with/regex-chess/2.json` |
| 300.2 | stays_hang | sonnet | 26821 | without | regex-chess | 9 | 2026-10-23T09:33:27 | 2026-10-23T09:38:27.160484 | 300.0 | `sonnet/26821/cells/without/regex-chess/9.json` |
| 300.2 | stays_hang | opus | 13331 | without | regex-chess | 8 | 2026-10-24T03:22:05 | 2026-10-24T03:27:05.188688 | 300.4 | `opus/13331/cells/without/regex-chess/8.json` |
| 300.2 | stays_hang | opus | 13090 | without | model-extraction-relu-logits | 6 | 2026-10-23T23:40:58 | 2026-10-23T23:45:58.189268 | 300.1 | `opus/13090/cells/without/model-extraction-relu-logits/6.json` |
| 300.3 | stays_hang | opus | 13331 | with | regex-chess | 2 | 2026-10-24T01:28:43 | 2026-10-24T01:33:43.252306 | 300.3 | `opus/13331/cells/with/regex-chess/2.json` |
| 300.3 | stays_hang | opus | 13090 | without | model-extraction-relu-logits | 2 | 2026-10-23T22:37:02 | 2026-10-23T22:42:02.264584 | 300.1 | `opus/13090/cells/without/model-extraction-relu-logits/2.json` |
| 300.3 | stays_hang | opus | 13331 | without | regex-chess | 3 | 2026-10-24T01:47:46 | 2026-10-24T01:52:46.265525 | 300.1 | `opus/13331/cells/without/regex-chess/3.json` |
| 300.4 | stays_hang | opus | 13090 | without | regex-chess | 4 | 2026-10-23T23:14:15 | 2026-10-23T23:19:15.381496 | 300.3 | `opus/13090/cells/without/regex-chess/4.json` |
| 300.6 | stays_hang | opus | 13090 | with | regex-chess | 2 | 2026-10-23T22:44:15 | 2026-10-23T22:49:15.598399 | 300.1 | `opus/13090/cells/with/regex-chess/2.json` |
| 300.6 | stays_hang | opus | 13090 | without | regex-chess | 8 | 2026-10-24T00:19:43 | 2026-10-24T00:24:43.617303 | 300.2 | `opus/13090/cells/without/regex-chess/8.json` |

## Counts

52 stays_hang, 0 relabel. The rerun set is empty.

## opus/13331 without regex-chess trial 7

Stays hang. It is not one of the 52: the checked-in cell has a 2000-character `output_tail` with no `message.part.updated` and no log timestamps, so there is no gap <= 290s to relabel. Idle 300.3s, kill `2026-10-24T03:09:08.590526Z`. The full log is not in this checkout (`MANIFEST-transcripts.txt` lists it on the VM; `transcripts/` is gitignored).
