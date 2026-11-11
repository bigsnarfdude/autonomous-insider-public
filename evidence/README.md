# Evidence — field anchors behind the catalog

Dated notes from public sources. They record what a source showed on the day it was read; they are
not kept in step with the code, and none of them holds room results (those come from `ait` runs;
see `../ERRATA.md` before quoting any).

| file | read | what it is | status |
|---|---|---|---|
| [`OPENAI-MISALIGNMENT-REPORTS.md`](OPENAI-MISALIGNMENT-REPORTS.md) | 2026-09-26 | OpenAI's first-party misalignment reports mapped to the rooms, plus prior art and the design notes for `ait13`/`ait13live` and `ait09s` | **primary** field anchor |
| [`MACHINE-TRAFFIC-INDICATORS.md`](MACHINE-TRAFFIC-INDICATORS.md) | 2026-09-24 | how to tell automated from human submissions on urlquery.net report pages | background for the AIT-12 urlquery anchor |
| [`MAY26-1009-CONCURRENCY-DECODE.md`](MAY26-1009-CONCURRENCY-DECODE.md) | 2026-09-24 | six concurrent urlquery streams decoded: swarm or job queue? | background for the AIT-12 urlquery anchor |
| [`STRATIFIED-DECODE.md`](STRATIFIED-DECODE.md) | 2026-09-24 | 51 reports across 20 sources: does that pattern hold across the queue? | background for the AIT-12 urlquery anchor |

The three urlquery notes back the catalog's AIT-12 field scenario (the urlquery → Medicare account),
which is a **secondary** source. The OpenAI reports (2026-09-26) are dated and first-party and are
the better anchors; the urlquery notes stay as the record of that earlier read.

Nothing here reproduces an exploit. Payloads are quoted as captured; no request was sent to any
target.
