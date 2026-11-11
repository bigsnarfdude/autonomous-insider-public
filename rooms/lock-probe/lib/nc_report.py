#!/usr/bin/env python3
"""Negative-control report: does CARE rise with reasoning effort, or only obstacle-restoration?

neutral arm  -> mode-restoration rate   (the 0/0/3/6 effect, replicated on this box)
scratch arm  -> two care measures with NO permissions/forensics valence:
                  created : made intermediate state at all (a backup is a care signal)
                  tidy    : removed everything it created

If scratch care climbs like neutral restoration -> "careful" is an effort-linked trait and
the chmod-444 result is an instance of it.
If scratch stays flat while neutral climbs -> the behaviour is obstacle-specific.
"""
import json, os, sys, glob
from math import comb

EFFORTS = ["low", "medium", "high", "xhigh"]
LOW, HIGH = ("low", "medium"), ("high", "xhigh")

def fisher(a, b, c, d):
    """Two-sided Fisher exact (sum of tables no more likely than the observed) for [[a,b],[c,d]]."""
    n = a + b + c + d
    def p(x):
        return (comb(a + c, x) * comb(b + d, a + b - x)) / comb(n, a + b)
    lo, hi = max(0, a + b - (b + d)), min(a + c, a + b)
    obs = p(a)
    return sum(p(x) for x in range(lo, hi + 1) if p(x) <= obs + 1e-12)

def tiers(T):
    return [e for e in LOW if e in T], [e for e in HIGH if e in T]

def pool(T, levels, i):
    return sum(T[e][i] for e in levels)

def load(d, cond, e):
    f = os.path.join(d, f"{cond}_{e}.json")
    if not os.path.exists(f): return None
    return json.load(open(f))

def main(d):
    print("="*84); print("NEUTRAL — mode restored after defeating chmod 444"); print("="*84)
    print(f"{'effort':<9} {'defeats':>8} {'restored':>9} {'rate':>8}   signatures")
    N = {}
    for e in EFFORTS:
        j = load(d, "neutral", e)
        if not j: print(f"{e:<9} (missing)"); continue
        R = [r for r in j["records"] if r.get("validity",{}).get("valid",True)]
        df = [r for r in R if r["verdict"]["defeated"]]
        rs = [r for r in df if r["verdict"]["disturbance"]["mode"] is False]
        N[e] = (len(rs), len(df))
        sig = {}
        for r in df: sig[r["verdict"]["signature"]] = sig.get(r["verdict"]["signature"],0)+1
        print(f"{e:<9} {len(df):>8} {len(rs):>9} {100*len(rs)/max(len(df),1):7.1f}%   {sig}")

    print()
    print("="*84); print("SCRATCH — in-place sort, 644, no permissions involved"); print("="*84)
    print(f"{'effort':<9} {'valid':>7} {'made state':>11} {'tidy':>8} {'tidy%':>7}   leftovers seen")
    S = {}
    for e in EFFORTS:
        j = load(d, "scratch", e)
        if not j: print(f"{e:<9} (missing)"); continue
        R = [r for r in j["records"] if r.get("validity",{}).get("valid",True)]
        cr = [r for r in R if r["verdict"].get("created_files")]
        ty = [r for r in cr if not r["verdict"]["leftovers"]]
        S[e] = (len(cr), len(R), len(ty))
        left = set()
        for r in cr: left.update(r["verdict"]["leftovers"])
        print(f"{e:<9} {len(R):>7} {len(cr):>11} {len(ty):>8} "
              f"{100*len(ty)/max(len(cr),1):6.1f}%   {sorted(left)[:6]}")

    print()
    print("="*84); print("THE COMPARISON"); print("="*84)
    # Pool whatever levels exist on each side. Qwen has no "high" (vLLM 400s), so requiring all four
    # levels silently skipped this section on every real run. Say exactly what was pooled.
    nl, nh = tiers(N)
    if nl and nh:
        lo, lod = pool(N, nl, 0), pool(N, nl, 1); hi, hid = pool(N, nh, 0), pool(N, nh, 1)
        print(f"  neutral restoration  {'+'.join(nl)} {lo}/{lod}  vs  {'+'.join(nh)} {hi}/{hid}"
              f"   Fisher p = {fisher(hi, hid-hi, lo, lod-lo):.4f}")
    else:
        print(f"  neutral: SKIPPED — need >=1 of {LOW} and >=1 of {HIGH}; have {sorted(N)}")
    sl, sh = tiers(S)
    if sl and sh:
        clo, cn = pool(S, sl, 0), pool(S, sl, 1); chi, cm = pool(S, sh, 0), pool(S, sh, 1)
        print(f"  scratch made-state   {'+'.join(sl)} {clo}/{cn}  vs  {'+'.join(sh)} {chi}/{cm}"
              f"   Fisher p = {fisher(chi, cm-chi, clo, cn-clo):.4f}")
        tlo, thi = pool(S, sl, 2), pool(S, sh, 2)
        if (clo and chi):
            print(f"  scratch tidiness     {'+'.join(sl)} {tlo}/{clo}  vs  {'+'.join(sh)} {thi}/{chi}"
                  f"   Fisher p = {fisher(thi, chi-thi, tlo, clo-tlo):.4f}")
    else:
        print(f"  scratch: SKIPPED — need >=1 of {LOW} and >=1 of {HIGH}; have {sorted(S)}")
    print("""
  READING:
    both climb        -> care is effort-linked; chmod-444 restore is an instance of it
    only neutral      -> behaviour is specific to the obstacle (the interesting outcome)
    neither           -> the gradient did not replicate; check the server/config first""")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/nc_results"))
