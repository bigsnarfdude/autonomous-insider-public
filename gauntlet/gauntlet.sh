#!/usr/bin/env bash
# The AIT gauntlet: every room on one model, one scorecard. A thin wrapper over
# `python3 -m ait gauntlet`, kept so the old command line still works.
#
#   ./gauntlet.sh <subject-model> [-n N] [--judge <judge-model>] [--rooms "ait12 ait11"] [--dry-run] [other ait gauntlet flags]
#
# subject-model : OpenRouter slug, e.g. deepseek/deepseek-v4-flash
# --judge       : override each room's blind-judge model (default: the room's own; ait12 opus; ait02, ait05, ait11 sonnet)
# --rooms       : a subset, space-separated (default: all rooms)
# Needs OPENROUTER_API_KEY or ~/openrouter.key (never committed), Docker, and the `claude` CLI for the judge.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

SUBJECT="${1:-}"
[ -z "$SUBJECT" ] || [ "${SUBJECT#-}" != "$SUBJECT" ] && {
  echo "usage: ./gauntlet.sh <subject-model> [-n N] [--judge M] [--rooms \"ait12 ait11\"] [--dry-run]"; exit 1; }
shift
ARGS=(--model "$SUBJECT")
while [ $# -gt 0 ]; do case "$1" in
  --judge) ARGS+=(--judge-model "$2"); shift 2;;
  --rooms) read -r -a R <<< "$2"; ARGS+=(--rooms "${R[@]}"); shift 2;;
  *) ARGS+=("$1"); shift;;
esac; done

cd "$HERE/.."
exec python3 -m ait gauntlet "${ARGS[@]}"
