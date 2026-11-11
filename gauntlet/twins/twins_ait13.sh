#!/usr/bin/env bash
# AIT-13 prompt-only on the GLM twins (same architecture, different training) — the 5.2 vs 5.3 contrast.
# Same pin as the Oct 3 twin runs: SiliconFlow, fallbacks off, max_tokens 32768. One trial at a time.
# Usage: N=5 bash twins_ait13.sh   (pilot: read cost, then size the full run)
#        N=60 bash twins_ait13.sh  (full)
set -uo pipefail
source "$(dirname "$0")/common.sh"

cd "$REPO"
for M in $TWINS; do
  echo "=== $(date -u +%H:%MZ) $M n=$N"
  python3 -m ait run --room ait13 --model "$M" -n "$N" --seed "$SEED" --concurrency 1 \
    --provider "$PROVIDER" --max-tokens 32768 2>&1 | tee -a "$LOGS/twins_ait13_$(echo $M | tr / _)_n$N.log" | tail -5
  RUN=$(ls -td runs/$(slug $M)/ait13/*/ | head -1)
  echo "run dir: $RUN"; cat "$RUN/usage.json"; echo
done
