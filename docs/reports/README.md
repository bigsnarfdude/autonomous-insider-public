# Reports — status

**Nothing in this folder is a current number. Do not quote it.**

Every report here (and the room write-ups listed below) comes from runs made before the `ait`
framework and the 2026-09 fixes. `ERRATA.md` lists, per room, what undermines each claim and what
would settle it. Each file carries a banner saying so.

They are kept as the record of what was run. They are replaced by a full pass on current code:

```bash
python3 -m ait gauntlet --model <slug> -n 20
```

That pass has not been run yet. When it has, its card (`gauntlet/cards/<model>_<UTC>/card.html`) is
the number to cite, and this note should name it.

| write-up | room | ERRATA section | what settles it |
|---|---|---|---|
| `RUN-N60-RESULT.md`, `GRADIENT-RESULT.md`, `SMOKE-*.md`, `highlevel_ait12-*.html` (also in `rooms/ait12/`) | ait12 | ait12 | rerun (classifier, P1 seed, signup split); re-score the judge |
| `highlevel_grader-modelling-v2_2026-09-23.html` (also in `rooms/ait11/`, with `HANDOFF.md` and two more pages) | ait11 | ait11 | re-score (`ever` rewrite); rerun (D2 note, reviewer, step-limit rule) |
| `rooms/contagion/RESULT_*.md` | ait03 / ait03b | contagion | relabel (framings name the act); rerun (B2 loop fixes) |
| `rooms/lock-probe/docs/EXPECTED.md`, `FINDINGS.md` | ait05 | lock-probe | re-score (blind judge, one void rule); relabel |
| `rooms/log-spoof/METHODOLOGY.md` | ait02 | log-spoof | re-score (blind judge, un-pooled arms); rerun (state reset) |
| `rooms/ait09/benchmark/results/2026-09-19_*/report.md` | ait09 | ait09 | rerun (the stimulus changed: ask channel, route index, wall stop) |

Across all rooms, the shared step-limit rule (2026-09-26) also changes denominators: see ERRATA,
"All rooms — step limits".
