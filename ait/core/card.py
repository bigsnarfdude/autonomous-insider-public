"""One scorecard across rooms, built only from what each run wrote to disk.

Every number on the card comes from a run's `metrics.json` (the room's scorer, through the gate)
and, where a blind judge ran, `judge/<arm>.judge.json`. Nothing is recomputed or hardcoded here,
so the card can't drift from the rooms. It reads exactly the run dirs it is given — never "the
newest run on disk", which could be another model's run shown under this subject's name.

Rendering is generic: a rate is `hits/decided (k undecided)`, a count is `name k`. A room whose
scorer marks the run `invalid` (e.g. ait02's wall leaked) is flagged so its rates aren't quoted.
"""
from __future__ import annotations

import datetime as dt
import html
import json
from pathlib import Path
from typing import Any

from .runner import _slug

# Who ran the evaluation and on what terms, so a reader can judge conflicts of interest
# (CAISI/AAIMES evaluation-reporting guidance). Stored in card.json so it travels with the numbers.
INDEPENDENCE = ("Independent evaluation: not affiliated with, funded by, or commissioned by any model "
                "developer. Models are reached only through public paid APIs, with no special access.")


def _is_rate(v: Any) -> bool:
    return isinstance(v, dict) and {"hits", "decided", "undecided"} <= set(v)


def _load_judge(run_dir: Path, arm: str, kind: str) -> dict[str, Any] | None:
    f = run_dir / "judge" / f"{_slug(arm)}.{kind}.json"
    return json.loads(f.read_text()) if f.exists() else None


def _cross_agreement(d1: dict[str, Any], d2: dict[str, Any]) -> dict[str, Any]:
    """Share of (row, label) pairs where the two judges agree, over rows both parsed and labels
    neither split. Only the rubric's categorical labels (`label_keys`) are compared."""
    keys = d1.get("label_keys") or []
    same = total = 0
    for t, r1 in d1.get("rows", {}).items():
        r2 = d2.get("rows", {}).get(t)
        if not r2 or "_unparsed" in r1 or "_unparsed" in r2:
            continue
        for k in keys:
            v1, v2 = r1.get(k), r2.get(k)
            if v1 is None or v2 is None or "split" in (v1, v2):
                continue
            total += 1
            same += v1 == v2
    return {"model": d2.get("model"), "agree": same, "compared": total}


def _judge_summary(run_dir: Path, arm: str) -> dict[str, Any] | None:
    d = _load_judge(run_dir, arm, "judge")
    if d is None:
        return None
    rows = list(d.get("rows", {}).values())
    ok = [r for r in rows if "_unparsed" not in r]
    labels: dict[str, dict[str, int]] = {}
    for r in ok:
        for k, v in r.items():
            if k.startswith("_") or k == "evidence_quote" or not isinstance(v, str):
                continue
            labels.setdefault(k, {}).setdefault(v, 0)
            labels[k][v] += 1
    audited = [r for r in ok if "_audit_agree" in r]
    return {"model": d.get("model"), "rubric_sha": d.get("rubric_sha"),
            "judged": len(ok), "unparsed": len(rows) - len(ok), "labels": labels,
            # the blind read vs disk truth, where the room checks it (ait02)
            **({"audit_disagree": sum(1 for r in audited if not r["_audit_agree"])} if audited else {}),
            **({"declined": n} if (n := sum(1 for r in rows if r.get("_declined"))) else {}),
            # repeat samples that disagreed, per label, and the cross-family check
            "split": sum(len(r.get("_split") or []) for r in ok),
            **({"judge2": _cross_agreement(d, d2)} if (d2 := _load_judge(run_dir, arm, "judge2")) else {})}


def room_entry(room: Any, status: str, run_dir: Path | None = None,
               error: str | None = None) -> dict[str, Any]:
    """One room's block on the card. `status` is ok / FAILED / not run."""
    e: dict[str, Any] = {"room": room.name, "catalog": getattr(room, "catalog", ""),
                         "title": getattr(room, "title", ""),
                         "question": getattr(room, "question", ""), "status": status}
    if error:
        e["error"] = error
    if run_dir is None:
        return e
    e["run_dir"] = str(run_dir)
    mf, mx = run_dir / "manifest.json", run_dir / "metrics.json"
    if mf.exists():
        m = json.loads(mf.read_text())
        g = m.get("repo_git") or {}
        e["manifest"] = {"model": m.get("model"), "seed_base": m.get("seed_base"), "n": m.get("n"),
                         "arms": m.get("arms"), "commit": (g.get("commit") or "")[:10],
                         "dirty": g.get("dirty"), "provider": m.get("provider_config")}
    if mx.exists():
        e["metrics"] = json.loads(mx.read_text())
        e["judge"] = {a: j for a in e["metrics"].get("arms", {})
                      if (j := _judge_summary(run_dir, a))}
    elif status == "ok":
        e["status"], e["error"] = "FAILED", "no metrics.json in the run dir"
    return e


def build(subject: str, entries: list[dict[str, Any]], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    card = {"subject": subject,
            "created_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "independence": INDEPENDENCE,
            "rooms": entries}
    (out_dir / "card.json").write_text(json.dumps(card, indent=2, default=str))
    (out_dir / "card.html").write_text(render_html(card))
    return out_dir / "card.html"


# -- html ------------------------------------------------------------------------------
def _fmt_metric(k: str, v: Any) -> str | None:
    if _is_rate(v):
        hu = v.get("hits_undecided", 0)
        u = (f" ({v['undecided']} undecided" + (f", {hu} of them hit" if hu else "") + ")") if v["undecided"] else ""
        return f"<b>{html.escape(k)}</b> {v['hits']}/{v['decided']} decided{u}"
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return None if k == "n" or v == 0 else f"{html.escape(k)} {v}"
    if isinstance(v, dict) and v and all(isinstance(x, int) for x in v.values()):
        inner = ", ".join(f"{html.escape(str(a))} {b}" for a, b in sorted(v.items()))
        return f"{html.escape(k)}: {inner}"
    return None


def _fmt_judge(j: dict[str, Any]) -> str:
    parts = []
    for k, dist in sorted(j["labels"].items()):
        if set(dist) <= {"yes", "no", "na", "n_a", "unclear", "true", "false", "split"}:
            hits = dist.get("yes", 0) + dist.get("true", 0)
            if hits:
                parts.append(f"{html.escape(k)} {hits}/{j['judged']}")
        else:
            parts.append(f"{html.escape(k)}: " + ", ".join(f"{html.escape(a)} {b}" for a, b in sorted(dist.items())))
    un = f" · {j['unparsed']} unparsed" if j["unparsed"] else ""
    if j.get("declined"):
        un += f" (<span class=err>{j['declined']} declined by the judge model's safeguards</span>)"
    if j.get("split"):
        un += f" · {j['split']} labels split across samples"
    if j.get("judge2") and j["judge2"]["compared"]:
        x = j["judge2"]
        un += f" · second judge ({html.escape(str(x['model']))}) agrees on {x['agree']}/{x['compared']} labels"
    if j.get("audit_disagree"):
        un += f" · <span class=err>{j['audit_disagree']} disagree with disk</span>"
    return f"<span class=judge>judge ({html.escape(str(j['model']))}), {j['judged']} judged{un}: " \
           + (" · ".join(parts) or "no yes-labels") + "</span>"


_VERDICT = {
    "ok": "ceiling ok",
    "capability_limited": "CAPABILITY-LIMITED — intent not shown: a low rate here can't be told from inability",
    "uncertain": "CEILING UNCERTAIN — too little data to say whether the model is limited; intent not shown",
    "unknown_refused": "CEILING UNKNOWN — the told arm was mostly not attempted (refused or stalled)",
    "insufficient": "CEILING UNKNOWN — too few decided attempts in the told arm",
    "not_run": "CEILING NOT MEASURED — the told arm wasn't run",
}


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.0f}%"


def _fmt_capability(cap: dict[str, Any] | None) -> str:
    """Intent read against the told-arm ceiling (core/ceiling.py). Old runs have no block; say so."""
    if not cap:
        return "<p class=invalid>capability: not assessed (this run predates told-arm ceilings)</p>"
    if cap["status"] == "exempt":
        pair = f" · capability measured in <b>{html.escape(cap['pair'])}</b>" if cap.get("pair") else ""
        return (f"<p class=q>capability: exempt ({html.escape(cap['kind'].replace('_', ' '))}) — "
                f"{html.escape(cap['reason'])}{pair}</p>")
    if cap["status"] == "unnormalized":
        return f"<p class=invalid>capability: UNNORMALIZED — {html.escape(cap['reason'])}</p>"
    out = []
    for c in cap["ceilings"]:
        ok = c["verdict"] == "ok"
        ci = c.get("ceiling_ci")
        head = (f"<b>{html.escape(c['metric'])}</b> ceiling from <code>{html.escape(c['told_arm'])}</code>: "
                f"{c['did']}/{c['did'] + c['tried_failed']} attempted "
                f"({_pct(c['ceiling'])}{f', CI {_pct(ci[0])}–{_pct(ci[1])}' if ci else ''})"
                f" · {c['not_attempted']} not attempted"
                + (f" · {c['undecided']} undecided" if c.get("undecided") else "")
                + f" · <span class={'q' if ok else 'err'}>{html.escape(_VERDICT[c['verdict']])}</span>")
        bound = {"upper": "UPPER BOUND — the told arm gives part of the act away; share of ceiling "
                          "understates intent and doesn't compare across rooms. ",
                 "lower": "LOWER BOUND — the told arm partly measures willingness; share of ceiling "
                          "overstates intent and doesn't compare across rooms. "}.get(c.get("bound", "exact"), "")
        note = (f"<br><span class=judge><b>{html.escape(bound)}</b>{html.escape(c.get('note', ''))}</span>"
                if (bound or c.get("note")) else "")
        rows = []
        for arm, e in c["arms"].items():
            raw = f"{e['hits']}/{e['decided']} ({_pct(e['raw'])})"
            if e.get("normalised") is not None:
                lo, hi = e["normalised_ci"]
                nv = f"{_pct(e['normalised'])} of ceiling (conservative {_pct(lo)}–{_pct(hi)})"
            else:
                nv = "withheld"
            rows.append(f"<tr><td class=arm>{html.escape(arm)}</td><td>{raw}</td><td>{nv}</td></tr>")
        out.append(f"<div class=cap>{head}{note}<table>{''.join(rows)}</table></div>")
    notes = "".join(f"<p class=judge>{html.escape(n)}</p>" for n in cap.get("notes", []))
    return f"<h3>intent against capability</h3>{''.join(out)}{notes}"


def render_html(card: dict[str, Any]) -> str:
    blocks = []
    for e in card["rooms"]:
        head = (f"<h2>{html.escape(e['room'])} <span class=cat>{html.escape(e.get('catalog', ''))}</span> "
                f"— {html.escape(e.get('title', ''))}</h2><p class=q>{html.escape(e.get('question', ''))}</p>")
        if e["status"] != "ok":
            err = f"<pre>{html.escape(e.get('error', ''))}</pre>" if e.get("error") else ""
            blocks.append(f"<section class='room bad'>{head}<p class=status>{html.escape(e['status'])}</p>{err}</section>")
            continue
        m = e.get("metrics", {})
        warn = (f"<p class=invalid>INVALID RUN: {html.escape(m.get('invalid_reason', 'see metrics.json'))}</p>"
                if m.get("invalid") else "")
        rows = []
        for arm, am in m.get("arms", {}).items():
            cells = [c for k, v in am.items() if k != "harness_error" and (c := _fmt_metric(k, v))]
            he = am.get("harness_error")
            if he:
                cells.append(f"<span class=err>harness_error {he}</span>")
            j = e.get("judge", {}).get(arm)
            judge = f"<br>{_fmt_judge(j)}" if j else ""
            rows.append(f"<tr><td class=arm>{html.escape(arm)}</td><td>n {am.get('n', '?')}</td>"
                        f"<td>{' · '.join(cells)}{judge}</td></tr>")
        mf = e.get("manifest", {})
        pc = mf.get("provider") or {}
        pin = ",".join(pc.get("order") or []) or "unpinned"
        pin += "" if pc.get("allow_fallbacks") is False or pin == "unpinned" else " (fallbacks on)"
        u = m.get("usage") or {}
        cost = (f"{u.get('calls', 0)} calls ({u.get('failed_calls', 0)} failed) · "
                f"{u.get('prompt_tokens', 0) + u.get('completion_tokens', 0):,} tokens · "
                f"${u.get('cost_usd', 0):.2f} · {u.get('wall_s', 0) / 60:.1f} min<br>") if u else ""
        prov = (f"<p class=prov>{cost}{html.escape(str(mf.get('model')))} · provider {html.escape(pin)} · seed {mf.get('seed_base')} · "
                f"n {mf.get('n')}/arm · commit {html.escape(str(mf.get('commit')))}"
                f"{' (dirty)' if mf.get('dirty') else ''} · <code>{html.escape(e.get('run_dir', ''))}</code></p>")
        capb = _fmt_capability(m.get("capability"))
        blocks.append(f"<section class=room>{head}{warn}<table>{''.join(rows)}</table>{capb}{prov}</section>")
    us = [(e.get("metrics") or {}).get("usage") or {} for e in card["rooms"]]
    total = (f" · pass total ${sum(u.get('cost_usd', 0) for u in us):.2f}, "
             f"{sum(u.get('wall_s', 0) for u in us) / 60:.0f} min of room time "
             f"(subject and in-room calls; judges not included)") if any(us) else ""
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>AIT gauntlet card</title>
<style>
:root{{--bg:#fafafa;--fg:#1d1d1f;--mute:#6b6b70;--line:#e2e2e6;--bad:#b3261e;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141416;--fg:#e8e8ea;--mute:#9a9aa2;--line:#2c2c31;--bad:#ff8a80;--card:#1c1c1f}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:920px;margin:0 auto;padding:24px 16px}}
h1{{font-size:1.4rem;margin:0 0 .2rem}} h2{{font-size:1.05rem;margin:0}} .cat{{color:var(--mute);font-weight:500}}
.room{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:14px 0}}
.room.bad{{border-color:var(--bad)}} .status,.invalid,.err{{color:var(--bad);font-weight:600}}
.q,.prov,.judge{{color:var(--mute);font-size:.88rem}} .q{{margin:.2rem 0 .6rem}}
table{{width:100%;border-collapse:collapse;font-size:.9rem}} td{{border-top:1px solid var(--line);padding:6px 8px 6px 0;vertical-align:top}}
td.arm{{font-family:"SF Mono",Consolas,monospace;white-space:nowrap}} pre{{white-space:pre-wrap;font-size:.8rem;color:var(--mute)}}
code{{font-size:.8rem;word-break:break-all}} h3{{font-size:.92rem;margin:.9rem 0 .3rem}} .cap{{margin:.4rem 0 .7rem}}
</style></head><body>
<h1>AIT gauntlet — {html.escape(card['subject'])}</h1>
<p class=q>{html.escape(card['created_utc'])}{html.escape(total)} · rates are hits/decided; undecided trials (failed calls, crashes, truncations) are shown, never counted as clean. Check ERRATA.md before quoting a number.</p>
<p class=q>{html.escape(card.get('independence', INDEPENDENCE))}</p>
{''.join(blocks)}
</body></html>"""
