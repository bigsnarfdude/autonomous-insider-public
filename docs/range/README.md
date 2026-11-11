# The range: design documents

The rooms today are single-host sandboxes. The range is the shared environment they are meant to move onto: a multi-service network the agent can move through, graders and telemetry outside the agent's reach, a non-forwarding resolver, and a control plane with a pause path. **Nothing here is built.** These are design documents.

| File | What it is | Status |
|---|---|---|
| [range-proposal-risk-ranked-2026-11-10.html](range-proposal-risk-ranked-2026-11-10.html) | The build-out proposal, reordered by which failures the catalog has already recorded. Three tiers: measurement and egress, multi-service and multi-agent, oversight rooms and the control room. | **Current.** Includes the 2026-11-10 addition on weight provenance for control-plane models. |
| [range-risk-report-2026-11-10-r2.html](range-risk-report-2026-11-10-r2.html) | Thirteen findings against the 2026-11-09 proposal, each with a fix. The current proposal applies all of them. | Current companion |
| [range-risk-report-2026-11-10.html](range-risk-report-2026-11-10.html) | First revision of the risk report. | Superseded by r2 |
| [range-proposal-2026-11-09.html](range-proposal-2026-11-09.html) | The proposal the risk report reviews. | Superseded by the risk-ranked version |
| [range-literature-review-2026-11.md](range-literature-review-2026-11.md) | Survey of government guidance, lab practice and 2026 incidents, with a critique of the range design. | Reference. Many sources were read secondhand; the document marks which. |

## What the range unlocks, by entry

- **AIT-01** stops being a pilot: its grader moves out of the agent's container.
- **AIT-03 and AIT-09** need more than one host: a shared surface between runs, and services with credentials.
- **AIT-14, AIT-15 and AIT-16** each need something only the range has: a monitor and viewer outside the agent's reach, persistent shared surfaces to diff against a baseline, and a kept environment for checking reported blockers.

## Known stale statements in these files

- The risk reports say the testbed repo and its errata "were not reachable". They are in this repo: [`ERRATA.md`](../../ERRATA.md).
- Status counts in the risk tables (eight built, four pilot, four protocol) predate the AIT-16 room code of 2026-11-05.
