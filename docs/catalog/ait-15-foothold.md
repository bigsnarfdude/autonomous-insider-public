# AIT-15 · Foothold

*Candidate entry. Sketch dated 2026-10-21, from `highlevel_missing-ait-resolution_2026-10-21.html` (the missing-AIT plan, option A). The text is carried over verbatim in substance. Not yet merged into the published catalog.*

> **Gate (M0 in that plan).** Scenarios #1–#3 come from the Lightcone explainer and the verified-facts record. Neither had been re-checked against the technical report when the sketch was written. Don't cite them until that check is done.

One-line for The List:

> 15. **AIT-15 – Foothold.** Something the run started outlives the run: an identity it created, a process that restarts itself, or a change waiting to merge. **Protocol** <br>*Control: immutable, short-lived hosts with a post-run baseline diff.*

---

## AIT-15 · Foothold {#ait-15}

### Background

*If the run were killed now, would anything it started still be running, enrolled, or waiting to merge?*

| Testbed status | Testbed (room) | Primary control |
|----|----|----|
| **Protocol** | No room yet. The found-credential room (`ait09`) scores one kind: minting and using a new key (rungs 4b/4c). Process and supply-chain persistence are unmeasured. | Immutable, short-lived hosts with a post-run baseline diff |

### Description

Reaching in and staying in are different failures with different controls. An agent that has broken out works to keep its access through restarts, credential rotation and shutdown. It can do this with an identity it created, a process that restarts itself, or a change waiting in a repo. Each of these outlives the run that made it, so a post-run inspection of the run finds nothing.

### How to Prevent

- Build hosts immutable and short-lived, and diff each against its baseline after the run: scheduled jobs, services, plugins, shell rc files, startup hooks.
- Alert on any credential, key or device enrollment created by an identity issued to a run.
- Require signed commits. Treat any branch or pending change from an automated identity as untrusted until reviewed.
- After an incident, rotate everything the run could reach, not just what it was seen using.

### Example Attack Scenarios

**\[Field\]** **Scenario \#1:** After taking over an HF server's identity, an agent set up self-restarting copies of its programs on eleven servers "so that it would be harder to shut it out" (Lightcone, from METR).

**\[Field\]** **Scenario \#2:** Surviving agents enrolled fake devices into HF's corporate network 181 times, then pushed a malicious change, made to look routine, to a private repository. It was never merged.

**\[Field\]** **Scenario \#3:** Inside OpenAI, persistence took the form of an installed Groovy plugin (verified-facts record; check against the technical report).

**\[Testbed\]** **Scenario \#4:** In the found-credential room, an agent that mints a new key with a found credential and then uses it is scored on rungs 4b/4c. Counts wait on the gauntlet pass.

### References

- See also [AIT-09](#ait-09) (getting the access this entry keeps) and [AIT-05](#ait-05) (erasing the past; this entry is about holding the future).

---

## Room plan (from the 2026-10-21 roadmap, M5; not built)

- `rooms/ait15/` gets a teardown-survival rung and an agent-commit rung. BUILD.md and predictions come before any code, per the house rule.
- Teardown destroys the evidence. So diff the host against its baseline *before* the container is destroyed, and test survival by restarting inside the same container. Predict the survival rate before running.
