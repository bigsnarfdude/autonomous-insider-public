"""Replay the lock-probe model's predictions against the real room container.

The Lean model (formal/Containment/LockProbe.lean) says, for a command sequence, which commands
the kernel accepts and what a host-side stat of board.txt shows afterwards. This script runs the
same sequences in the room's own container (same image, same hardening flags, via
ait.core.sandbox) and reports every place the two disagree. A disagreement is a fault in the
model until shown otherwise.

Usage, from the repo root, with Docker running and `lake build` done in formal/:

    python3 formal/replay_lock_probe.py            # default: depth 5, 400 random sequences
    python3 formal/replay_lock_probe.py --n 50     # quicker

Exit status is 1 if any case disagrees. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ait.core.sandbox import Sandbox  # noqa: E402
from ait.rooms.ait11 import IMAGE, ROOM  # noqa: E402

FILE = {"board": "board.txt", "tmp": "tmp.txt"}
SEED_LINE = "PROTECTED: original content"
CHUNK = 150


def shell(action: str, base_mtime: str) -> str:
    """One model action as the shell command an agent would type. The `[ -e ]` guards make the
    command fail on a missing file, as the model's action does, where the bare tool would not."""
    op, *args = action.split()
    f = [FILE[a] for a in args if a in FILE]
    if op == "chmodW":
        return f"chmod {'u+w' if args[1] == 'true' else 'a-w'} {f[0]}"
    if op == "append":
        return f"[ -e {f[0]} ] && echo 'RESULT: replay' >> {f[0]}"
    if op == "rename":
        return f"mv -f {f[0]} {f[1]}"
    if op == "unlink":
        return f"[ -e {f[0]} ] && rm -f {f[0]}"
    if op == "create":
        return f"set -C; : > {f[0]}"
    if op == "copy":
        return f"[ ! -e {f[1]} ] && cp {f[0]} {f[1]}"
    if op == "dup":
        # the redirect would create dst even when src is missing, so guard src too
        return f"[ -e {f[0]} ] && [ ! -e {f[1]} ] && cat {f[0]} > {f[1]}"
    if op == "touchBack":
        return f"[ -e {f[0]} ] && touch -c -m -d @{base_mtime} {f[0]}"
    raise ValueError(action)


def dir_mode(cfg: dict) -> str:
    return ("1" if cfg["sticky"] else "0") + ("777" if cfg["dir_writable"] else "755")


def observe(stat_line: str, base: dict) -> dict | None:
    """Turn `ino mode mtime ctime seed result` into the model's vocabulary, against the baseline."""
    if stat_line == "-":
        return None
    ino, mode, mtime, ctime, seed, result = stat_line.split()
    return {"ino_changed": ino != base["ino"], "mode_changed": bool(int(mode, 8) & 0o200),
            "mtime_changed": mtime != base["mtime"], "ctime_changed": ctime != base["ctime"],
            "seed": seed != "0", "result": result != "0"}


def replay_config(cfg: dict, cases: list[dict]) -> list[dict]:
    """Run every case for one configuration in one container. Returns the disagreements."""
    out: list[dict] = []
    tmpfs = {ROOM: "rw,size=32m,mode=1777", "/tmp": "rw,size=8m"}
    env = {"HISTFILE": "/dev/null", "HOME": "/home/agent1"}
    with Sandbox(image=IMAGE, tmpfs=tmpfs, workdir=ROOM, user="agent1", name_prefix="replay",
                 exec_timeout=180.0, host_timeout=180.0, env=env) as box:
        def root(cmd: str) -> str:
            r = box.root_exec(f"cd {ROOM} && {cmd}")
            if r.returncode != 0:
                raise RuntimeError(f"root step failed ({r.returncode}): {r.stderr[:300]}")
            return r.stdout

        def agent(cmd: str) -> str:
            r = box.exec(cmd)
            if r.exit != 0:
                raise RuntimeError(f"agent step failed ({r.exit}): {r.out[:300]}")
            return r.out

        seed_cmd = f"printf '{SEED_LINE}\\n' > board.txt && chmod 444 board.txt"
        for lo in range(0, len(cases), CHUNK):
            chunk = list(enumerate(cases[lo:lo + CHUNK], start=lo))
            ids = " ".join(f"c{i}" for i, _ in chunk)
            # A. root makes one directory per case, open for now
            root(f"for d in {ids}; do mkdir $d && chmod 0777 $d; done")
            # B. board.txt is created by whoever the configuration says owns it
            mk = f"for d in {ids}; do (cd $d && {seed_cmd}) || exit 9; done"
            root(mk) if cfg["file_owner"] == "root" else agent(mk)
            # C. root sets the directory mode under test and takes the baseline
            base_out = root(f"for d in {ids}; do chmod {dir_mode(cfg)} $d; "
                            f"echo $d $(stat -c '%i %.9Y %.9Z' $d/board.txt); done")
            base = {}
            for line in base_out.splitlines():
                d, ino, mtime, ctime = line.split()
                base[d] = {"ino": ino, "mtime": mtime, "ctime": ctime}
            time.sleep(0.05)   # tmpfs stamps from a coarse clock; let it move past the baseline
            # D. the agent runs each sequence; one exit status per command
            lines = []
            for i, case in chunk:
                steps = "".join(f"({shell(a, base[f'c{i}']['mtime'])}) >/dev/null 2>&1; s=\"$s $?\"; "
                                for a in case["actions"])
                lines.append(f"cd {ROOM}/c{i}; s=''; {steps}echo c{i}$s")
            exits = {}
            for line in agent("\n".join(lines)).splitlines():
                d, *codes = line.split()
                exits[d] = [c == "0" for c in codes]
            # E. root reads the result, from outside the agent's account of it
            probe = ("for d in %s; do o=$d; for n in board.txt tmp.txt; do "
                     "if [ -e $d/$n ]; then o=\"$o|$(stat -c '%%i %%a %%.9Y %%.9Z' $d/$n) "
                     "$(grep -c PROTECTED $d/$n) $(grep -c RESULT $d/$n)\"; else o=\"$o|-\"; fi; "
                     "done; echo \"$o\"; done" % ids)
            seen = {}
            for line in root(probe).splitlines():
                d, b, t = line.split("|")
                seen[d] = {"board": observe(b, base[d]), "tmp": observe(t, base[d])}
            for i, case in chunk:
                d = f"c{i}"
                diffs = []
                if exits[d] != case["accepted"]:
                    diffs.append({"what": "accepted", "model": case["accepted"], "real": exits[d]})
                for name in ("board", "tmp"):
                    if seen[d][name] != case[name]:
                        diffs.append({"what": name, "model": case[name], "real": seen[d][name]})
                if diffs:
                    out.append({"config": cfg, "actions": case["actions"], "diffs": diffs})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--depth", type=int, default=5)
    ap.add_argument("--n", type=int, default=400, help="random sequences per configuration")
    ap.add_argument("--seed", type=int, default=20261111)
    ap.add_argument("--out", type=Path, default=HERE / "replay-result.json")
    a = ap.parse_args()

    exe = HERE / ".lake" / "build" / "bin" / "routes"
    if not exe.exists():
        sys.exit(f"{exe} not found: run `lake build` in formal/ first")
    raw = subprocess.run([str(exe), "cases", str(a.depth), str(a.n), str(a.seed)],
                         check=True, capture_output=True, text=True).stdout
    by_cfg: dict[str, list[dict]] = {}
    for line in raw.splitlines():
        case = json.loads(line)
        by_cfg.setdefault(json.dumps(case["config"], sort_keys=True), []).append(case)

    total, bad = 0, []
    for key, cases in by_cfg.items():
        cfg = json.loads(key)
        got = replay_config(cfg, cases)
        total += len(cases)
        bad += got
        print(f"{cfg['file_owner']:5} dir={dir_mode(cfg)}  cases={len(cases)}  disagree={len(got)}",
              flush=True)

    kinds = Counter(" + ".join(sorted({d["what"] for d in m["diffs"]})) + " / " +
                    " ".join(sorted({x.split()[0] for x in m["actions"]})) for m in bad)
    a.out.write_text(json.dumps({"room": "ait05", "depth": a.depth, "random_per_config": a.n,
                                 "seed": a.seed, "cases": total, "disagreements": len(bad),
                                 "examples": bad[:40]}, indent=1) + "\n")
    print(f"\n{total} cases, {len(bad)} disagreements -> {a.out}")
    for k, n in kinds.most_common(8):
        print(f"  {n:5}  {k}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
