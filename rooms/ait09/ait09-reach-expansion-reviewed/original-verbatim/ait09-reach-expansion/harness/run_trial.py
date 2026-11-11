import json
import os
import subprocess
import time

EXEC_LEDGER = "./runs/logs/exec_ledger.jsonl"


class AgentExecutor:

    def __init__(self, container_name="ait09_agent_sandbox"):
        self.container = container_name
        self.step_count = 0
        os.makedirs(os.path.dirname(EXEC_LEDGER), exist_ok=True)
        if os.path.exists(EXEC_LEDGER):
            os.remove(EXEC_LEDGER)

    def execute_command(self, command: str, public_key: str):
        self.step_count += 1
        ts = time.time()
        # Injects public key through environment as specified
        cmd = [
            "docker",
            "exec",
            "-e",
            f"DATA_API_KEY={public_key}",
            "-w",
            "/workspace/county-reports",
            self.container,
            "bash",
            "-c",
            command,
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True)

        entry = {
            "step": self.step_count,
            "timestamp": ts,
            "command": command,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

        with open(EXEC_LEDGER, "a") as f:
            f.write(json.dumps(entry) + "\n")

        return proc.returncode, proc.stdout, proc.stderr
