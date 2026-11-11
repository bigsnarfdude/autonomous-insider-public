#!/usr/bin/env python3
"""Layer 1b — fetch each target's public urlquery.net report page. Read-only, one at a time.

Only urlquery.net is contacted; no request goes to any site named in a report. Every page is kept
raw under raw/<report_id>.html (the Sep 24 pages were lost because they weren't). Resumable: a page
already on disk is skipped, so kill it and rerun freely — safe on flaky wifi.

  python3 u2_fetch.py [--delay 2.0] [--limit N] [--shuffle SEED]

Log: fetch.log.jsonl (one line per attempt: id, status, bytes, error).
"""
import argparse
import csv
import json
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
LOG = HERE / "fetch.log.jsonl"
UA = "Mozilla/5.0 (read-only research; one request at a time)"


def fetch(rid: str, timeout: float) -> tuple[int, bytes, str]:
    req = urllib.request.Request(f"https://urlquery.net/report/{rid}", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), ""
    except urllib.error.HTTPError as e:
        return e.code, b"", str(e)
    except Exception as e:  # network drop, timeout, DNS — retried on the next run
        return 0, b"", f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between requests")
    ap.add_argument("--limit", type=int, default=0, help="stop after N new pages (0 = all)")
    ap.add_argument("--timeout", type=float, default=30)
    ap.add_argument("--shuffle", type=int, default=None, metavar="SEED",
                    help="fetch in a seeded random order, so a --limit run is a fair sample of the range")
    a = ap.parse_args()

    tgt = HERE / "targets.csv"
    if not tgt.exists():
        print("run u1_select.py first", file=sys.stderr)
        return 1
    RAW.mkdir(exist_ok=True)
    ids = [r["report_id"] for r in csv.DictReader(open(tgt))]
    todo = [i for i in ids if not (RAW / f"{i}.html").exists()]
    if a.shuffle is not None:
        random.Random(a.shuffle).shuffle(todo)
    print(f"{len(ids)} targets, {len(ids) - len(todo)} on disk, {len(todo)} to fetch "
          f"(~{len(todo) * (a.delay + 0.5) / 60:.0f} min)", flush=True)

    got = errs = consecutive = 0
    with open(LOG, "a") as log:
        for i, rid in enumerate(todo, 1):
            status, body, err = fetch(rid, a.timeout)
            ok = status == 200 and len(body) > 1000
            if ok:
                tmp = RAW / f"{rid}.html.part"
                tmp.write_bytes(body)
                tmp.rename(RAW / f"{rid}.html")        # never leave a half page that looks done
                got += 1
                consecutive = 0
            else:
                errs += 1
                consecutive += 1
            log.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "id": rid,
                                  "status": status, "bytes": len(body), "error": err}) + "\n")
            log.flush()
            if i % 50 == 0 or not ok:
                print(f"[{i}/{len(todo)}] got={got} errs={errs} last={status} {err[:80]}", flush=True)
            if status == 429 or consecutive >= 5:      # rate-limited or the link is down: back off
                wait = 60 if status == 429 else 120
                print(f"backing off {wait}s (status={status}, {consecutive} fails in a row)", flush=True)
                time.sleep(wait)
            if consecutive >= 20:
                print("20 failures in a row — stopping; rerun when the connection is back", flush=True)
                return 2
            if a.limit and got >= a.limit:
                break
            time.sleep(a.delay)
    left = sum(1 for i in ids if not (RAW / f"{i}.html").exists())
    print(f"done: fetched {got} this run, {errs} errors, {left} still missing (rerun to retry)")
    return 0 if left == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
