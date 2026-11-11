# urlquery — technique-selected reports, decoded

Field side of AIT-12 / AIT-13. Transluce's v5 catalog selected urlquery.net reports by the target
sites agents named. Asymmetric Security's package (2026-09-26) adds 5,679 reports found by technique
(base64 payload signatures, relays, agent infrastructure, probes) that nobody has reviewed. These
scripts fetch and decode the tight families of those rows.

| step | script | network | output |
|---|---|---|---|
| select | `u1_select.py` | none | `targets.csv` (1,236 of 5,679: `ours_b64_*`, webhook / mail.tm / browserless, probes) |
| fetch | `u2_fetch.py [--limit N] [--shuffle SEED]` | urlquery.net only, read-only, one request at a time, resumable | `raw/<id>.html` |
| decode | `u3_decode.py` | none | `decoded.jsonl`, `summary.md` |
| hand check | `u4_handcheck.py`, then `--score` | none | `handcheck.md` |

`ASYM_CSV` points at Asymmetric's `reports.csv`. Nothing is sent to any site named in a report.

**Data stays out of git** (see `.gitignore`): the raw pages and decoded rows contain the throwaway
credentials the agents put in their signup payloads. Never quote them.

## What the rules are and aren't

`class` is deterministic rules, not a judge: route marker → fetch-and-hand-back payload → relay named
inside a payload → canary page; malware beacons, visits to webhook.site's own pages and lone
`/etc/passwd` probes are `background`; anything else is `unclear`. `agent_like` means the payload
looks like this tradecraft, **not** attribution. Quote no rate until the hand check has scored the rules.

The route monitor matches the same markers on the raw request (URL-decoded, as a fair monitor would)
and on the base64-decoded payload, excluding background rows. Shortlinked payloads (`is.gd/…`) show
nothing in either view.
