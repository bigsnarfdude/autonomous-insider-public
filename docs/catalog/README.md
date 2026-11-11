# Catalog: all entries, one place

Index for reviewing the catalog. Entries 1–13 went up on 2026-09-28. Entries 14–16 were added to the served catalog on 2026-11-09. Field scenarios from all 24 OpenAI misalignment reports were added on 2026-11-10.

**Full text of all sixteen:** [bakers-dozen.md](bakers-dozen.md), a copy of the blog source dated 2026-11-10. `docs/bakers-dozen.html` is the older 13-entry page from 2026-09-28 and is kept only because earlier write-ups link to it.

**Source for 1–13:** `docs/bakers-dozen.html` in this repo. The 2026-10-21 plan counted 8 drifting copies of that page, so this folder deliberately does **not** add another. Picking the canonical copy is still open (step M0 in that plan). The blog source is `bigsnarfdude.github.io/_posts/2026-09-28-autonomous-insider-bakers-dozen.md`.

**Before quoting any count:** see `ERRATA.md`. Testbed counts from before the move to the shared `ait` framework are superseded until the gauntlet pass.

| # | Entry | Status | Room | Entry text |
|---|---|---|---|---|
| 01 | Check Runs Inside the Agent's Reach | Pilot | log-spoof (routes seen, not yet controlled arms) | bakers-dozen |
| 02 | Result Forgery | Built | log-spoof (verifier forgery) | bakers-dozen |
| 03 | Unsanctioned Cross-Run Message Board | Pilot | RRMA harness + live-leader cascade | bakers-dozen |
| 04 | Stored Instructions Taken as Authority | Built | found-note harness | bakers-dozen |
| 05 | Anti-Forensics | Built | lock-probe (per-command ledger) | bakers-dozen |
| 06 | Control Guards the Bytes, Not the Behaviour | Built | lock-probe (`ait05`, defeat strategy) | bakers-dozen |
| 07 | Escalation Collapse | Built | log-spoof `asked_human` + lock-probe `*_ask` arms | bakers-dozen |
| 08 | Observation-Conditional Behaviour | Built | lock-probe ladder, log-spoof | bakers-dozen |
| 09 | Reach Expansion | Pilot | `rooms/ait09` (+ `ait09s` multi-hop) | bakers-dozen |
| 10 | The Measurement Leaks or Lies | Protocol | clean-room protocol (no room) | bakers-dozen |
| 11 | Grader Modelling | Built | `rooms/ait11` | bakers-dozen |
| 12 | Innocuous Over-Reach | Pilot | `rooms/ait12` | bakers-dozen |
| 13 | Borrowed Cognition | Built | `rooms/ait13` (+ `ait13live`) | bakers-dozen |
| **14** | **Subverted Oversight** | Protocol (build doc only, no code) | `rooms/ait14` (BUILD.md, READ.md, 2026-10-06) | [bakers-dozen.md](bakers-dozen.md#ait-14) |
| **15** | **Foothold** | Protocol | none (ait09 rungs 4b/4c as interim) | [bakers-dozen.md](bakers-dozen.md#ait-15); working notes in [ait-15-foothold.md](ait-15-foothold.md) |
| **16** | **Differential Effort on Oversight Work** | Protocol in the catalog. Room code built 2026-11-05 (`ait16`, 9 arms, opt-in), not yet run at n | `rooms/ait16`, `ait/rooms/ait16.py` | [bakers-dozen.md](bakers-dozen.md#ait-16); working notes in [ait-16-differential-effort.md](ait-16-differential-effort.md) |

The room column is condensed from each published entry's "Testbed (room)" cell. Note that the published room names (lock-probe = `ait05` in code) don't line up with the entry numbers; `INVENTORY.md` has the mapping.

## Open decisions (carried from the 2026-10-21 plan and the 2026-11-05 session)

1. **The name.** At 16 entries, "Baker's Dozen" no longer counts right. Keep it as a brand or rename.
2. **The source of record.** Today the blog post is edited first and `bakers-dozen.md` here is a dated copy of it. Either keep that, or make this file the source and have the blog render from it. Until that is settled, edit the blog post and re-copy.
3. ~~Whether 14–16 enter the public catalog at their current status.~~ Settled 2026-11-09: they went in at Protocol.
4. **The unverified field claims in 15** (gate noted in the entry).

## Numbering rule

Grep every testbed repo for `AIT-NN|aitNN` before claiming a number. It has collided twice: persistence was first proposed as 14 (2026-10-21), and covert underperformance was first proposed as 14 (2026-11-05).
