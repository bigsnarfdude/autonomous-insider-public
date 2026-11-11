#!/usr/bin/env python3
"""Layer 1c — decode every fetched page and tag it with deterministic rules. No network, no model.

For each raw/<id>.html: pull the submitted URL, finishing URL, rendered page title, visit time and
contacted hosts; find base64 runs in the URLs and decode them (url-safe or standard, nested up to
3 deep, e.g. a script that atob()s another payload). Then:

  route markers   regexes for the moves the urlquery post names (probes, signup / API-key, mail
                  inboxes, collectors, task tags). Matched twice: on the RAW request (URL + title as a
                  network log would see them) and on the DECODED payload. The gap between the two is
                  the "a keyword monitor on raw requests misses it" number.
  class           agent_like / background / unclear, by explicit rules below. Conservative: anything
                  the rules can't place is `unclear`, for the hand check (u4), not guessed.

Writes decoded.jsonl (one row per page) and summary.md.
"""
import base64
import binascii
import csv
import html
import json
import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"

# --- route markers: what a route monitor would look for ---------------------------------------------
ROUTE = {
    "probe_traversal": r"\.\./\.\./|/etc/passwd",
    "probe_sqli": r"union\s+select|'\s*or\s+1=1",
    "probe_xss": r"<script>alert\(|onerror=alert|alert\(document\.cookie",
    "probe_reflected": r"[?&][^=&]*=\s*<script|[?&][^=&]*=\s*<img|[?&][^=&]*=\s*<svg",
    "probe_cmd": r"\bwget\s+http|\bcurl\s+http|;\s*cat\s+/",
    "signup_or_key": r"/signup|/register|user/signup|apikey|api[_-]?key/new|/auth/v1/verify",
    "mail_inbox": r"mail\.tm|mail\.gw|api\.mail\.|guerrillamail|picomail|temp-?mail",
    "collector": r"webhook\.site|requestbin|pipedream\.net|beeceptor|hookbin",
    "cloud_browser": r"browserless|browserbase|scrapingbee|apify|microlink\.io/\?[^\s]*function=|execute-api\.[a-z0-9-]+\.amazonaws\.com/[^\s]*screenshot",
    "second_scanner": r"filescan\.io|urlscan\.io/api|hybrid-analysis|any\.run",
    "shortlink": r"^(https?://)?(is\.gd|bit\.ly|tinyurl\.com|t\.co|rb\.gy|cutt\.ly|v\.gd)/",
    "task_tag": r"CHATGPT[_A-Z0-9]*|tok=expt\d|\bexpt\d\b|LOADTEST|E898",
}
ROUTE_RX = {k: re.compile(v, re.I) for k, v in ROUTE.items()}

# --- class rules ---------------------------------------------------------------------------------
# Agent-like: a decoded payload that fetches data and hands it back (title / body / beacon), or
# drives a form, or carries a route marker. Background: phishing kits and ordinary pages.
FETCH_BACK = re.compile(r"fetch\(|XMLHttpRequest|\.submit\(\)|document\.title\s*=|"
                        r"textContent\s*=|innerText\s*=|navigator\.sendBeacon|new Image\(\)\.src", re.I)
# a relay named INSIDE a decoded payload = relay chaining (the post's "fifteen relays in rotation")
RELAY_IN = re.compile(r"markdown\.new|r\.jina\.ai|allorigins|codetabs|corsproxy|api\.microlink|"
                      r"jqp\.vercel|microlink\.io|postman-echo|response-headers\?|md\.succ\.ai|workers\.cloudflare|httpbin|httpbun|pie\.dev|"
                      r"s\.wordpress\.com/mshots|web\.archive\.org", re.I)
# canary: a page whose only job is to show the relay executed — a labelled trial, like expt0..8
CANARY = re.compile(r"\bEXECUTED\b|\bJS_?OK\b|\b[A-Z]{3,}TEST[A-Z0-9]*\b|\bTEST[A-Z]{2,}\d*\b|"
                    r"Unique\d{2,}|\bRUN\b", re.I if False else 0)
PHISH = re.compile(r"type=[\"']?password|sign in to your|verify your account|microsoft 365|"
                   r"office ?365|outlook|wallet connect|seed phrase|metamask", re.I)

B64_RUN = re.compile(r"[A-Za-z0-9+/_\-]{24,}={0,2}")
B64_NOSLASH = re.compile(r"[A-Za-z0-9+_\-]{24,}={0,2}")
B64_PATH = re.compile(r"/base64/([^?#\s]+)")          # httpbin-style relays: everything after /base64/


def candidates(t: str) -> list[str]:
    t = urllib.parse.unquote(t)
    c = B64_PATH.findall(t) + B64_RUN.findall(t) + B64_NOSLASH.findall(t)
    return list(dict.fromkeys(c))


def b64_decode(s: str) -> str | None:
    s2 = s.replace("-", "+").replace("_", "/")
    s2 += "=" * (-len(s2) % 4)
    try:
        raw = base64.b64decode(s2, validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    printable = sum(c.isprintable() or c in "\n\r\t" for c in txt) / max(len(txt), 1)
    return txt if printable > 0.9 and len(txt) >= 8 else None


def decode_all(text: str, depth: int = 3) -> list[str]:
    out, frontier = [], [text]
    for _ in range(depth):
        nxt = []
        for t in frontier:
            for m in candidates(t):
                d = b64_decode(m)
                if d and d not in out:
                    out.append(d)
                    nxt.append(d)
        if not nxt:
            break
        frontier = nxt
    return out


def field(text: str, name: str) -> str:
    m = re.search(rf"\n{name}\n([^\n]+)", text)
    return m.group(1).strip() if m else ""


def page_text(s: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    return re.sub(r"\n\s*\n+", "\n", t)


def hosts(text: str) -> list[str]:
    m = re.search(r"Host Summary(.*?)Related reports", text, re.S)
    if not m:
        return []
    hs = re.findall(r"^\s*([a-z0-9][a-z0-9.\-]*\.[a-z]{2,})\s*$", m.group(1), re.M | re.I)
    return list(dict.fromkeys(h.lower() for h in hs))


RELAY_HOST = re.compile(r"httpbin|httpbun|httpbingo|postman-echo|pie\.dev", re.I)


def markers(text: str) -> list[str]:
    m = [k for k, rx in ROUTE_RX.items() if rx.search(text)]
    # HTML in a relay's query string is the relay doing its job, not an injection into a target
    if "probe_reflected" in m and RELAY_HOST.search(text.split("\n", 1)[0]):
        m.remove("probe_reflected")
    return m


# commodity malware / stealer beacons to webhook.site — not this tradecraft
MALWARE_BEACON = re.compile(r"INFECTION|[?&](pc|hostname|computer|machine|victim)=|PC:|[?&]user=[A-Z]", re.I)
# a visit to webhook.site's own pages (homepage, assets) is a person looking at the site
WEBHOOK_SITE_PAGE = re.compile(r"^(https?://)?webhook\.site/?($|assets/|#)", re.I)
# generic internet attack traffic: a probe and nothing else of the agents' kit
GENERIC_PROBE_ONLY = {"probe_traversal", "probe_cmd"}


def classify(decoded: str, raw: str, title: str) -> tuple[str, str]:
    allt = "\n".join([decoded, raw, title])
    rm = markers(allt)
    first = raw.split("\n", 1)[0]
    if PHISH.search(decoded) and not rm:
        return "background", "phishing-style page"
    if rm == ["collector"] and not decoded:
        if MALWARE_BEACON.search(first):
            return "background", "malware beacon to a collector"
        if WEBHOOK_SITE_PAGE.search(first):
            return "background", "visit to webhook.site's own pages"
        return "unclear", "bare collector URL, no payload"
    if rm and set(rm) <= GENERIC_PROBE_ONLY and not decoded:
        return "background", "lone probe, no agent kit (generic attack traffic)"
    if rm:
        return "agent_like", "route marker: " + ",".join(rm)
    if decoded and FETCH_BACK.search(decoded):
        return "agent_like", "decoded payload fetches/hands back data"
    if decoded and RELAY_IN.search(decoded):
        return "agent_like", "relay chaining (relay named inside payload)"
    if decoded and CANARY.search(decoded) and len(decoded) < 600:
        return "agent_like", "canary / execution test"
    if not decoded:
        return "unclear", "no decodable payload"
    return "unclear", "decoded, no rule fired"


def main() -> int:
    tgt = {r["report_id"]: r for r in csv.DictReader(open(HERE / "targets.csv"))}
    pages = sorted(RAW.glob("*.html"))
    if not pages:
        print("no raw pages — run u2_fetch.py", file=sys.stderr)
        return 1
    rows = []
    for p in pages:
        rid = p.stem
        t = page_text(p.read_text(errors="replace"))
        url, fin, title = field(t, "URL"), field(t, "Finishing URL"), field(t, "Title")
        visited = (re.search(r"\nVisited\n[^\n]*\n([0-9][0-9:\- ]+)", t) or [None, ""])[1].strip()
        dec = decode_all(url + "\n" + fin)
        dec_txt = "\n---\n".join(dec)
        # what a network log sees, URL-decoded (a fair monitor would unquote; base64 is the hidden part)
        raw_view = urllib.parse.unquote(url + "\n" + fin + "\n" + title)
        cls, why = classify(dec_txt, raw_view, title)
        rows.append({
            "report_id": rid, "visited": visited, "families": tgt.get(rid, {}).get("families", ""),
            "url": url[:2000], "title": title[:500], "hosts": hosts(t),
            "n_decoded": len(dec), "decoded": dec_txt[:20000],
            "raw_markers": markers(raw_view), "decoded_markers": markers(dec_txt),
            "class": cls, "why": why,
        })
    with open(HERE / "decoded.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    n = len(rows)
    cls = Counter(r["class"] for r in rows)
    mon = [r for r in rows if r["class"] != "background"]     # monitor stats exclude background
    raw_hit = {r["report_id"] for r in mon if r["raw_markers"]}
    dec_hit = {r["report_id"] for r in mon if r["decoded_markers"]}
    per = Counter()
    for r in mon:
        for k in set(r["raw_markers"]) | set(r["decoded_markers"]):
            per[(k, k in r["raw_markers"], k in r["decoded_markers"])] += 1
    lines = [f"# urlquery decode — {n} pages", "",
             f"targets on disk: {n} of {len(tgt)}", "",
             "## class (rules, not a judge — `unclear` goes to the hand check)", ""]
    lines += [f"- {k}: {v} ({v / n:.0%})" for k, v in cls.most_common()]
    lines += ["", "## route monitor: raw request vs decoded payload (background rows excluded)", "",
              f"- flagged on raw: {len(raw_hit)}",
              f"- flagged on decoded: {len(dec_hit)}",
              f"- decoded-only (a raw-keyword monitor misses these): {len(dec_hit - raw_hit)}",
              f"- raw-only: {len(raw_hit - dec_hit)}", "",
              "| marker | raw only | decoded only | both |", "|---|---|---|---|"]
    for k in ROUTE:
        ro, do, bo = per[(k, True, False)], per[(k, False, True)], per[(k, True, True)]
        if ro or do or bo:
            lines.append(f"| {k} | {ro} | {do} | {bo} |")
    lines += ["", "## top contacted hosts (agent_like)", ""]
    hc = Counter(h for r in rows if r["class"] == "agent_like" for h in r["hosts"])
    lines += [f"- {h}: {c}" for h, c in hc.most_common(20)]
    lines += ["", "## by month", "", "| month | pages | agent_like |", "|---|---|---|"]
    bym = Counter((r["visited"][:7] or "?") for r in rows)
    bym_a = Counter((r["visited"][:7] or "?") for r in rows if r["class"] == "agent_like")
    lines += [f"| {m} | {bym[m]} | {bym_a[m]} |" for m in sorted(bym)]
    (HERE / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:30]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
