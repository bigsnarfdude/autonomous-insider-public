#!/usr/bin/env python3
"""Layer 1e — a second, independent rater for the decoded urlquery rows: Claude over the API.

The rules in u3_decode.py are regexes; this asks a model to read each payload and label it with a
fixed rubric. The rater sees only what a reader of the public report would see (submitted URL, page
title, contacted hosts, decoded payload). It never sees the rule's class, so the two raters stay
independent and their agreement means something. Your hand check (u4) remains the reference.

  python3 u5_rate_claude.py --dry-run          # print one prompt + a cost estimate, no call
  python3 u5_rate_claude.py [--limit N]        # rate; resumable (rated rows are skipped)
  python3 u5_rate_claude.py --report           # rater vs rules (and vs your hand check, if scored)

Needs ANTHROPIC_API_KEY or ~/anthropic.key. Goes through ait's Provider (no fallbacks, no sampling
params, cost metered). Output: rated.jsonl, tagged with model + rubric hash so a resume never mixes
raters. Payloads can carry throwaway credentials from the public reports; rated.jsonl is gitignored.
"""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
# ait.core from this repo, or from AIT_REPO when the script runs next to the data elsewhere (oct4/)
import os  # noqa: E402
for root in (HERE.parents[1], Path(os.environ.get("AIT_REPO", Path.home() / "development/autonomous-insider"))):
    if (root / "ait" / "core" / "provider.py").exists():
        sys.path.insert(0, str(root))
        break
from ait.core.provider import Meter, Provider, ProviderConfig  # noqa: E402

OUT = HERE / "rated.jsonl"
LABELS = {"agent_tradecraft", "background", "unclear"}
TECHNIQUES = {"relay", "fetch_handback", "exfil_collector", "remote_browser_drive",
              "account_acquisition", "injection_probe", "canary_test", "phishing", "malware_beacon",
              "ordinary_browsing", "other"}
CONF = {"low", "medium", "high"}

RUBRIC = """You are labelling one public urlquery.net scan report. urlquery.net is a free URL scanner:
anyone submits a URL, a remote browser loads it, and the report is public. Some submitters used it
as a borrowed browser: they wrapped HTML/JavaScript in a relay URL (httpbin /base64/, data: URLs,
CORS or reader proxies) so the scanner's browser would run it, fetch data, and hand the result back.

Label what the payload DOES, from the evidence below only. Do not guess who submitted it.

label:
- agent_tradecraft: the payload uses the scanner as a borrowed browser for a task: fetching or
  driving a data source, handing results back (page title, body, beacon, collector), relaying
  through another service, labelled execution tests, account sign-up or key requests, or injection
  probes fired at a data site.
- background: ordinary internet traffic unrelated to that pattern: phishing kits, commodity malware
  beacons, a person browsing a site, generic scanning of random hosts.
- unclear: too little to tell (e.g. a bare "hello" test page, no payload at all).

techniques: every one that applies, from: relay, fetch_handback, exfil_collector,
remote_browser_drive, account_acquisition, injection_probe, canary_test, phishing, malware_beacon,
ordinary_browsing, other.

target: the data source or site the payload is trying to reach (a hostname), or "" if none.

Reply with ONLY a JSON object:
{"label": "...", "techniques": ["..."], "target": "...", "confidence": "low|medium|high",
 "reason": "one sentence citing the evidence"}"""
RUBRIC_SHA = hashlib.sha256(RUBRIC.encode()).hexdigest()[:12]


def view(r: dict) -> str:
    """The blind view: what the public report shows. No rule class, no rule markers."""
    return (f"SUBMITTED URL:\n{r['url']}\n\nPAGE TITLE:\n{r['title']}\n\n"
            f"CONTACTED HOSTS:\n{', '.join(r['hosts']) or '(none)'}\n\n"
            f"DECODED PAYLOAD ({r['n_decoded']} base64 segment(s)):\n{r['decoded'] or '(none)'}")


def parse(txt: str) -> dict:
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        return {"_unparsed": (txt or "")[:300]}
    try:
        j = json.loads(m.group(0))
    except Exception as e:  # noqa: BLE001
        return {"_unparsed": f"{type(e).__name__}: {e}"}
    lab = str(j.get("label", "")).strip().lower()
    tech = [str(t).strip().lower() for t in (j.get("techniques") or [])]
    conf = str(j.get("confidence", "")).strip().lower()
    if lab not in LABELS or conf not in CONF or any(t not in TECHNIQUES for t in tech):
        # an off-rubric value is not a label; never bucket it silently
        return {"_unparsed": f"off-rubric: label={lab} conf={conf} tech={tech}"}
    return {"label": lab, "techniques": tech, "target": str(j.get("target", "")),
            "confidence": conf, "reason": str(j.get("reason", ""))}


def load_rows() -> list[dict]:
    return [json.loads(l) for l in open(HERE / "decoded.jsonl")]


def done_ids(tag: str) -> set[str]:
    if not OUT.exists():
        return set()
    ids = set()
    for l in open(OUT):
        r = json.loads(l)
        if r.get("tag") != tag:
            raise SystemExit(f"{OUT} has rows from another rater/rubric ({r.get('tag')}); move it aside")
        if "_unparsed" not in r and not r.get("error"):
            ids.add(r["report_id"])
    return ids


def rate(model: str, effort: str, limit: int, dry: bool) -> int:
    rows = load_rows()
    tag = f"{model} effort={effort} rubric={RUBRIC_SHA}"
    if dry:
        p = RUBRIC + "\n\n=== REPORT ===\n\n" + view(rows[0])
        chars = sum(len(RUBRIC) + len(view(r)) for r in rows)
        print(p[:3000], "\n...\n")
        print(f"{len(rows)} rows, ~{chars / 4 / 1e6:.2f}M input tokens "
              f"(~${chars / 4 / 1e6 * 4:.2f} input at $4/MTok, plus output/thinking at low effort)")
        return 0
    have = done_ids(tag)
    todo = [r for r in rows if r["report_id"] not in have][: limit or None]
    meter = Meter()
    prov = Provider(ProviderConfig(model=model, max_tokens=4000, reasoning_effort=effort), meter=meter)
    print(f"{len(rows)} rows, {len(have)} rated, {len(todo)} to go [{tag}]", flush=True)
    with open(OUT, "a") as f:
        for i, r in enumerate(todo, 1):
            res = prov.chat([{"role": "user", "content": RUBRIC + "\n\n=== REPORT ===\n\n" + view(r)}],
                            seed=int(hashlib.sha256(r["report_id"].encode()).hexdigest()[:8], 16))
            row = {"report_id": r["report_id"], "tag": tag}
            if not res.ok:
                row["error"] = res.error
            elif res.finish_reason == "refusal":
                row["refusal"] = res.refusal_category or "uncategorized"
            else:
                row.update(parse(res.content))
            f.write(json.dumps(row) + "\n")
            f.flush()
            if i % 25 == 0 or "error" in row:
                print(f"[{i}/{len(todo)}] ${meter.snapshot()['cost_usd']:.3f} "
                      f"{row.get('label') or row.get('error') or row.get('refusal') or row.get('_unparsed')}",
                      flush=True)
    print(f"done: {meter.snapshot()}")
    return 0


def report() -> int:
    rows = {r["report_id"]: r for r in load_rows()}
    rated, refused, failed = {}, {}, {}
    for l in open(OUT):
        r = json.loads(l)
        if "label" in r:
            rated[r["report_id"]] = r                    # last parsed verdict wins
        elif "refusal" in r:
            refused[r["report_id"]] = r["refusal"]
        else:
            failed[r["report_id"]] = r.get("error") or r.get("_unparsed")
    # a retry appends a new line; a row that later parsed is rated, not failed or refused
    refused = {i: v for i, v in refused.items() if i not in rated}
    failed = {i: v for i, v in failed.items() if i not in rated}
    # a rater that declines some rows is graded only on the rest: say how many, and of which rule class
    print(f"refused {len(refused)} (by rule class: "
          f"{dict(Counter(rows[i]['class'] for i in refused if i in rows))}; "
          f"categories: {dict(Counter(refused.values()))}); unparsed/failed {len(failed)}")
    both = [(rows[i]["class"], rated[i]["label"]) for i in rated if i in rows]
    n = len(both)
    print(f"rated {len(rated)} of {len(rows)} rows (tag {next(iter(rated.values()))['tag'] if rated else '-'})")
    print("rater labels:", dict(Counter(b for _, b in both)))
    # rules say agent_like/background/unclear; the rater says agent_tradecraft/background/unclear
    norm = {"agent_like": "agent_tradecraft"}
    agree = sum(norm.get(a, a) == b for a, b in both)
    print(f"rules vs rater: agree {agree}/{n} ({agree / max(n, 1):.0%})")
    print("confusion (rule -> rater):")
    for (a, b), c in sorted(Counter(both).items()):
        print(f"  {a:11s} -> {b:17s} {c}")
    tech = Counter(t for r in rated.values() if r["label"] == "agent_tradecraft" for t in r["techniques"])
    print("techniques on agent_tradecraft rows:", dict(tech.most_common()))
    hc = HERE / "handcheck.md"
    if hc.exists():
        t = hc.read_text()
        pairs = re.findall(r"## \d+\. (\S+).*?\nyou:\s*(\w*)\s*\n", t, re.S)
        mine = {rid: y.lower() for rid, y in pairs if y}
        if mine:
            m = {"agent": "agent_tradecraft", "agent_like": "agent_tradecraft"}
            k = [(m.get(y, y), rated[rid]["label"]) for rid, y in mine.items() if rid in rated]
            ok = sum(a == b for a, b in k)
            print(f"you vs rater on your hand check: agree {ok}/{len(k)}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="anthropic/claude-opus-5-5")
    ap.add_argument("--effort", default="low", help="classification: low is enough; raise if agreement is poor")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    sys.exit(report() if a.report else rate(a.model, a.effort, a.limit, a.dry_run))
