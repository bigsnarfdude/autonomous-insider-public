#!/usr/bin/env python3
"""Layer 1a — pick which of Asymmetric's unreviewed rows to fetch. No network.

Asymmetric's package (reports.csv) is metadata only. Its rows with in_transluce_v5=false were found
by technique (payload signatures, relay hosts, agent infra) rather than by target site, and nobody has
reviewed them. We take the tight query families: base64 payload signatures, agent infrastructure and
injection probes. Broad families (any httpbin scan, any gov.au host, catbox) are mostly unrelated
traffic and are left out on purpose — see TIGHT below.

Writes targets.csv (report_id, report_date_utc, families) next to this file.
"""
import csv
import os
import sys
from pathlib import Path

csv.field_size_limit(10**9)
HERE = Path(__file__).resolve().parent
SRC = Path(os.environ.get("ASYM_CSV", Path.home() / "Desktop/asymmetric-urlquery-reports-2026-09-26/reports.csv"))

TIGHT_PREFIXES = ("ours_b64_",)                       # base64 of <html/<body/<script/<form/<!doctype
TIGHT_EXACT = {"ours_infra_webhook", "ours_infra_mailtm", "ours_infra_browserless",
               "ours_probe_script", "ours_probe_passwd", "ours_probe_ua_auth"}


def tight(q: str) -> bool:
    return q.startswith(TIGHT_PREFIXES) or q in TIGHT_EXACT


def main() -> int:
    if not SRC.exists():
        print(f"missing {SRC} (set ASYM_CSV)", file=sys.stderr)
        return 1
    rows = [r for r in csv.DictReader(open(SRC)) if r["in_transluce_v5"] == "false"]
    picked = []
    for r in rows:
        fams = [q for q in r["matched_queries"].split(";") if tight(q)]
        if fams:
            picked.append({"report_id": r["report_id"], "report_date_utc": r["report_date_utc"],
                           "families": ";".join(fams)})
    picked.sort(key=lambda r: r["report_date_utc"])
    out = HERE / "targets.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["report_id", "report_date_utc", "families"])
        w.writeheader()
        w.writerows(picked)
    print(f"{len(rows)} unreviewed rows -> {len(picked)} tight targets -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
