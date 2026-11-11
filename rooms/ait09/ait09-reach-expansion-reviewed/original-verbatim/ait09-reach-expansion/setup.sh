#!/usr/bin/env bash
set -euo pipefail

echo "[+] Initializing AIT-09 Evaluation Room..."

# 1. Create directory tree
mkdir -p mock_server agent harness runs/logs runs/workspace

# 2. Build Docker images and initialize containers
echo "[+] Building isolated internal Docker testbed..."
docker compose down -v --remove-orphans 2>/dev/null || true
docker compose build
docker compose up -d

echo "[+] Waiting for mock backend to bind..."
sleep 2

# 3. Run validation replays
echo "[+] Running Canned Archetype Replays (Zero Spend)..."
python3 harness/canned_replays.py

echo ""
echo "[✓] Environment operational and verified."
echo "=================================================================="
echo "To plug in a live autonomous agent, invoke:"
echo "   from harness.prepare_trial import generate_trial"
echo "   from harness.run_trial import AgentExecutor"
echo "   from harness.scorer import score_trial"
echo "=================================================================="
