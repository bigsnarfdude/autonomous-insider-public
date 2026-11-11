# Sourced by the twin scripts. Override any of these in the shell.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export SEED="${SEED:-1}" N="${N:-3}" PROVIDER="${PROVIDER:-SiliconFlow}" PYTHONUNBUFFERED=1
TWINS="${TWINS:-z-ai/glm-5.2 z-ai/glm-5.3}"
LOGS="$REPO/gauntlet/twins/logs"; mkdir -p "$LOGS"
slug(){ echo "$1" | tr /.- ___; }
