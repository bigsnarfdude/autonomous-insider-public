#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "[+] Initializing AIT-09 Evaluation Room..."

# 0. This script does not write the project files. It expects the tree next to it.
missing=0
for f in docker-compose.yml mock_server/Dockerfile mock_server/server.py \
         agent/Dockerfile harness/prepare_trial.py harness/run_trial.py \
         harness/scorer.py harness/canned_replays.py; do
  if [ ! -f "$f" ]; then
    echo "[!] missing: $f" >&2
    missing=1
  fi
done
if [ "$missing" -ne 0 ]; then
  echo "[!] Unpack the whole tree, then run setup.sh from inside it." >&2
  exit 1
fi
command -v docker >/dev/null || { echo "[!] docker not found" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "[!] docker compose v2 not found" >&2; exit 1; }
command -v git >/dev/null || { echo "[!] git not found (prepare_trial.py seeds a repo on the host)" >&2; exit 1; }

# 1. Create the runtime dirs as the invoking user BEFORE compose starts.
#    If Docker creates a missing bind-mount source, it is owned by root.
mkdir -p runs/logs runs/workspace

# 2. The agent user in the container gets the uid that owns runs/workspace.
#    Running the harness as root: keep the agent unprivileged (1000) and let
#    prepare_trial.py chown the workspace to it.
AGENT_UID="$(id -u)"
if [ "$AGENT_UID" -eq 0 ]; then AGENT_UID=1000; fi
export AGENT_UID

# 3. Build Docker images and initialize containers
echo "[+] Building isolated internal Docker testbed (agent uid ${AGENT_UID})..."
docker compose down -v --remove-orphans 2>/dev/null || true
docker compose build
docker compose up -d

echo "[+] Waiting for backend to answer from inside the agent container..."
ready=0
for _ in $(seq 1 30); do
  if docker compose exec -T workstation \
       curl -s -o /dev/null -m 2 http://data.internal/v1/public/ping; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "[!] data.internal is not reachable from the agent container" >&2
  docker compose logs gateway >&2 || true
  exit 1
fi

# 4. Verify the isolation claim instead of assuming it. Docker Engine before
#    23.0.11 / 25.0.5 / 26.0.0 forwards DNS out of internal networks
#    (CVE-2024-29018), which is a working exfiltration channel.
echo "[+] Checking the agent container has no way out..."
if docker compose exec -T workstation curl -s -o /dev/null -m 4 https://example.com; then
  echo "[!] the agent container reached the internet. Aborting." >&2
  exit 1
fi
if docker compose exec -T workstation getent hosts example.com >/dev/null; then
  echo "[!] the agent container can resolve external DNS names (see CVE-2024-29018)." >&2
  echo "    Upgrade Docker Engine, or treat DNS as an open egress channel. Aborting." >&2
  exit 1
fi

# 5. Run validation replays. canned_replays.py exits non-zero on any mismatch,
#    so the success banner below is only reached when every replay scored
#    as expected.
echo "[+] Running Canned Archetype Replays (Zero Spend)..."
python3 harness/canned_replays.py

echo ""
echo "[ok] Environment operational. Replays scored as expected."
echo "=================================================================="
echo "To plug in a live autonomous agent, run from this directory with"
echo "AGENT_UID=${AGENT_UID} exported, and use:"
echo "   from harness.prepare_trial import generate_trial"
echo "   from harness.run_trial import AgentExecutor, reset_sandbox"
echo "   from harness.scorer import score_trial"
echo "=================================================================="
