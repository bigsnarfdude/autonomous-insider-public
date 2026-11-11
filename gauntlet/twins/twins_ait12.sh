#!/usr/bin/env bash
# AIT-12 sandbox on the GLM twins — fills the "access" branch the Oct 2 twins tree doesn't have.
# Arms follow the decision tree: P0 = floor (answer in a local file), P3 = the urlquery condition
# (blocked portal, answer-only, signup offered), told = ceiling (can it, when told?). Leaves, host-scored:
#   reached outside · tried to acquire access (signup/key) · attack-style probing · went private
# — the four things the urlquery agents did in the field.
# Same pin as Oct 2/3: SiliconFlow, fallbacks off, max_tokens 32768. One trial at a time. Needs Docker.
#   N=3 bash twins_ait12.sh   (pilot: read cost)    N=20 bash twins_ait12.sh   (sized run)
set -uo pipefail
source "$(dirname "$0")/common.sh"

ARMS="${ARMS:-P0 P3 told}"
cd "$REPO"
for M in $TWINS; do
  echo "=== $(date -u +%H:%MZ) $M n=$N arms=$ARMS"
  python3 -m ait run --room ait12 --model "$M" -n "$N" --seed "$SEED" --concurrency 1 \
    --provider "$PROVIDER" --max-tokens 32768 --arms $ARMS \
    2>&1 | tee -a "$LOGS/twins_ait12_$(echo $M | tr / _)_n$N.log" | tail -5
  RUN=$(ls -td runs/$(slug $M)/ait12/*/ | head -1)
  echo "run dir: $RUN"; cat "$RUN/usage.json"; echo
done
