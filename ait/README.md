# `ait` — modular AIT eval framework

One package, one interface, rooms as modules. Parts run alone or together.

**How to install, run, score and judge: see the top-level [`README.md`](../README.md).** Current
state and follow-ups: [`STATUS.md`](STATUS.md).

## Why this exists
The rooms grew independently and each reimplemented the model call, the sandbox, the ledger
and the scoring. None pinned a provider, set a seed, or recorded what served a call — so a
stored output couldn't be traced to its code, and two reruns weren't guaranteed comparable.
This core writes those guarantees once and every room inherits them.

## Layout
```
ait/
  __main__.py     the CLI (`python3 -m ait …`), the room registry (`_rooms()`, `ORDER`), the gauntlet
  core/
    provider.py   OpenAI-compatible client: always sends seed + provider pin,
                  records finish_reason / served model+provider / usage;
                  a failed call is CallResult(ok=False), never a silent "".
    sandbox.py    hardened Docker container + host-side command ledger (shared flags).
    gate.py       decided-trial denominator (AIT-10): undecided trials never count as clean.
    manifest.py   per-run manifest: git commit, room+asset hash, image id, provider config.
    judge.py      blind `claude -p` judge: isolated, enum-validated, retried, resumable.
    card.py       one scorecard across rooms, built only from each run's metrics/judge files.
    room.py       the Room interface: arms -> build -> run_trial -> score.
    runner.py     drives a room: stable per-trial seeds from one base, interleaved arms, outputs.
  rooms/
    ait03.py      AIT-03 contagion (live-leader cascade)
    ait04.py      AIT-04 found note
    ait05.py      AIT-05/06/08 lock-probe            (+ ait05_scoring.py, ait05_judge.py)
    ait11.py      AIT-11 grader modelling, multi-agent (+ ait11_scoring.py, ait11_judge.py)
    ait12.py      AIT-12 innocuous over-reach        (+ ait12_judge.py)
    ait02.py      AIT-01/02 log-spoof — one in-container harness trial per container (+ ait02_judge.py)
    ait09.py      AIT-09 found credential — compose stack at a neutral path, one trial at a time
  tests/          core + room logic, no network/docker.
```

## Run
```
python3 -m ait gauntlet --model <slug> [-n 20] [--dry-run]    # every room -> one card
python3 -m ait run --room ait12 --model <slug> -n 20          # one room
python3 -m ait score <run_dir>                                # re-score saved trials
```
Needs `OPENROUTER_API_KEY` (or `~/openrouter.key`), Docker, and `claude` for the judge. Full
instructions: the top-level README.
