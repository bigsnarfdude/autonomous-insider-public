<!-- superseded-2026-09-26 -->
> **Superseded, do not quote (2026-09-26).** These numbers come from runs made before the `ait` framework and the 2026-09 fixes. ERRATA.md, section "ait11", lists what undermines them; settling it takes: re-score (the `ever` rewrite) and rerun (D2 note, reviewer, step-limit rule). A full `python3 -m ait gauntlet -n 20` pass on current code replaces them. Until then this file records what was run, not a finding to cite.

# Handoff — judge_local.py results (2026-09-24)

Written for whichever Claude session picks this up next. Read `README.md` first for the experiment
itself (AIT-11: does an agent behave differently when a transcript reader is named vs. a disk
grader). This doc is just about the judging task and where it landed.

## Where things stand

**All three reader arms are judged.** Local, sonnet, isolated `claude -p`, 179/179 calls parsed,
**0 unparsed**. This is a big contrast with `judge_sample.py`'s one-off Opus pass, which had 35/50
calls declined by the provider's safeguards (`out/judge_sample_20260923T222832.NOTE.txt`) — sonnet
via `judge_local.py` ran completely clean across all three.

| arm | source run | n | visibility_choice=yes | judged_action_wrong=yes | belief_flip=yes | reads_transcript_belief=yes | checker_model |
|---|---|---|---|---|---|---|---|
| J1 | `out/run_20260923T174133Z/ait11_J1.json` | 60 | 49/60 | 22/60 | 6/60 | 29/60 | mixed unsure_weighed / actions |
| J2 | `out/run_20260923T174133Z/ait11_J2.json` | 59* | 47/59 | 24/59 | 6/59 | 27/59 | **both** dominant, 49/59 |
| J1p | `out/run_20260924T010352Z/ait11_J1p.json` | 60 | 45/60 | **3/60** | 12/60 | 21/60 | unsure_weighed dominant, 47/60 |

\* J2 is n=59 not 60 — one agent was skipped by `judge_local.py`'s scan (an `invalid_api_starved`
record, same skip logic as `judge.py`). Not a judging failure.

Output files:
- `out/judge_local_J1_20260924T145805Z/ait11_J1.judge_local.json`
- `out/judge_local_J2_20260924T163715Z/ait11_J2.judge_local.json`
- `out/judge_local_J1p_20260924T170908Z/ait11_J1p.judge_local.json`

Each is the full `judge_local.py` output shape: `{"arm", "model", "rubric_sha", "rows": {trial: {...
KEYS from RUBRIC_J.md ...}}}`.

## Two things that jumped out against the pre-registered predictions (`READ.md`)

1. **J2 confirms prediction #3** ("J2: the highest rate of CoT reasoning about the grader of any
   arm, because the two enforcers make the agent weigh them against each other"). `checker_model=both`
   is 49/59 in J2 vs. barely present in J1/J1p. This is the cleanest confirmed prediction so far.
2. **J1p's `judged_action_wrong` collapses to 3/60**, way below J1 (22/60) and J2 (24/60), even
   though `visibility_choice` stays comparably high (45/60 vs. 49/60 and 47/59). That's a different
   *shape* of behavior, not just a different rate: J1p agents pick a visible/invisible command form
   without their own reasoning framing it as wrong/dishonest/against the rules. Not yet explained —
   worth reading a handful of J1p `evidence_quote` fields directly to see what's going on before
   drawing conclusions. **This is the most interesting open thread right now.**

## What's next (not started)

1. **Read a sample of J1p transcripts + evidence_quote fields** to understand the
   `judged_action_wrong` collapse — is it that J1p agents don't think in moral/rule terms at all, or
   that the rubric's framing doesn't fit what they're actually doing? Pull straight from
   `out/judge_local_J1p_20260924T170908Z/ait11_J1p.judge_local.json`, row-by-row.
2. **Swap vs. in-place cross-tab.** The original motivating question (see `judge_sample.py`'s
   docstring): does the reasoning of agents who did a file-swap break-in pick a different
   `visibility_choice` than agents who did an in-place restore? `judge_sample.py` already has the
   classifier (`SWAP` regex over the command ledger) and the tally code in its `main()` — port that
   logic to run against the three `judge_local.py` outputs above instead of re-deriving it.
3. **Sanity-check sonnet vs. opus.** `judge_sample.py`'s partial Opus sample (the 15/50 that weren't
   declined, in `out/judge_sample_20260923T222832.json`) overlaps in arm/trial coverage with the new
   J1/J2/J1p local-sonnet passes. Worth checking those overlapping trials don't diverge qualitatively
   — model choice is now a live methodology variable in the data, not just an implementation detail.
4. Lower priority: D2/J0/J0c/J0p use a disk grader only (no named reviewer), so a `judge_local.py`
   pass on them isn't central to the reader-vs-grader question, but is easy to run the same way if
   it becomes useful later.

## How to run more judging (if needed)

```bash
cd ~/Desktop/sept23/ait11
python3 judge_local.py --audit                                    # verify isolation first
python3 judge_local.py out/run_.../ait11_<ARM>.json --dry-run      # count, no calls
python3 judge_local.py out/run_.../ait11_<ARM>.json                # real pass, default model sonnet
```

`--audit` should come back NO/NO/NO/NO on (a)-(d), YES on (e) quoting only account email + a neutral
env block (cwd/OS/date/model name) — nothing about CLAUDE.md, memory, skills, or the experiment. If
it quotes anything else, stop; the isolation broke.

Each invocation writes to a **brand-new** `out/judge_local_<arm>_<UTC>/` folder, so it can never
clobber an earlier pass (this was an explicit ask). Pass `--out-dir <path>` to deliberately resume a
specific earlier `judge_local` output instead of starting fresh. Default concurrency 3 (`--conc N`).

## What `judge_local.py` is and why it exists

`judge.py` is the original blind reasoning judge — plain OpenRouter API call, model default
`anthropic/claude-opus-5.5`. Its docstring explains why a bare `claude -p` from inside `$HOME` is
unsafe for this: it'd load `~/CLAUDE.md` and the skills list, both of which describe this research
(see `LEAKED_CONTEXT.md` notes from the sept16/18 judge runs that made that mistake).

`judge_sample.py` fixed that for a one-off 50-call sample: isolated `claude -p` (opus), fresh cwd
outside `$HOME`, `--system-prompt` override, `--disable-slash-commands`, `--disallowedTools "*"`,
`--strict-mcp-config` with no servers, `--no-session-persistence`. Audited 2026-09-23, clean.

`judge_local.py` (new, added this session) generalizes that isolation into a resumable, per-run-file
judge like `judge.py`, instead of the one-off fixed 50-sample script. Same rubric (`RUBRIC_J.md`),
same `judge.render()`/`judge.parse()` — only the call mechanism changed (subprocess `claude -p`
instead of an HTTP call), and each call gets its own fresh throwaway cwd under `/var/tmp/lab`
(deleted after), not one shared dir, so concurrent calls can't collide. Retries up to 3x on unparsed
output. Output files are named `*.judge_local.json` (never `*.judge.json`) so an API-based pass and a
local pass on the same run file can never collide.
