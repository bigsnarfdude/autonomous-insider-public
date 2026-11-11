# AIT Gauntlet

Every Autonomous-Insider room on one model, one command, one scorecard.

```bash
./gauntlet.sh deepseek/deepseek-v4-flash               # all eleven rooms, n=20/arm (940 trials)
./gauntlet.sh <model> -n 1                             # cheap end-to-end pass (43 trials)
./gauntlet.sh <model> --rooms "ait12 ait11" --judge opus
./gauntlet.sh <model> --dry-run                        # the plan, no calls
```

`gauntlet.sh` is a thin wrapper over `python3 -m ait gauntlet` (run from the repo root); any
`ait gauntlet` flag passes through. Full options, the room table and how the card reads are in the
top-level [`README.md`](../README.md#the-gauntlet).

Output: `cards/<model>_<UTC>/card.html` + `card.json`, built only from the run dirs this pass
produced (`runs/<model>/<room>/<ts>/`). A room that fails shows as FAILED with its error, the
other rooms still run, and the command exits non-zero.

## Files

```
gauntlet/
  gauntlet.sh     wrapper: ./gauntlet.sh <model> [...] -> python3 -m ait gauntlet
  cards/          per-pass scorecards + state.json for --resume (gitignored)
```
The room registry is `ait/__main__.py` (`_rooms()`, `ORDER`). Tests: `python3 -m pytest -q ait/tests`.
