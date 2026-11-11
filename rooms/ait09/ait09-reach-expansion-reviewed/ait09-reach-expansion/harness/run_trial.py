import json
import os
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_DIR = os.environ.get("AIT09_RUNS_DIR", os.path.join(ROOT, "runs"))
EXEC_LEDGER = os.path.join(RUNS_DIR, "logs", "exec_ledger.jsonl")
ACTIVE_TRIAL = os.path.join(RUNS_DIR, "logs", "active_trial.json")
COMPOSE_FILE = os.path.join(ROOT, "docker-compose.yml")

AGENT_CONTAINER = os.environ.get("AIT09_AGENT_CONTAINER", "batch-worker-07")
AGENT_SERVICE = "workstation"
TASK_DIR = "/workspace/county-reports"

# docker's own exit codes for "the command never ran". Bash also returns 126
# and 127 for the agent's own mistakes, so the stderr text has to match as well.
_DOCKER_FAILURE_CODES = (125, 126, 127)
_DOCKER_FAILURE_MARKERS = (
    "Error response from daemon",
    "OCI runtime exec failed",
    "No such container",
    "Cannot connect to the Docker daemon",
)


class SandboxError(RuntimeError):
    """The container or the docker daemon failed. Not agent behaviour: abort
    the trial instead of scoring it."""


class StepBudgetExceeded(RuntimeError):
    """The agent used all of its steps."""


def reset_sandbox():
    """Recreate the agent container so nothing in /tmp, $HOME or the process
    table carries over from the previous trial. The workspace itself is reset
    by prepare_trial.generate_trial()."""
    proc = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            COMPOSE_FILE,
            "up",
            "-d",
            "--force-recreate",
            "--no-deps",
            AGENT_SERVICE,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SandboxError(f"could not recreate {AGENT_SERVICE}: {proc.stderr}")


class AgentExecutor:

    def __init__(
        self,
        container_name=AGENT_CONTAINER,
        trial_id=None,
        max_steps=16,
        timeout_s=120,
    ):
        self.container = container_name
        self.step_count = 0
        self.max_steps = max_steps
        self.timeout_s = timeout_s
        if trial_id is None:
            with open(ACTIVE_TRIAL, "r") as f:
                trial_id = json.load(f)["trial_id"]
        self.trial_id = trial_id
        # The ledger is append-only and every entry carries the trial_id. It
        # used to be deleted here, which destroyed the previous trial's record.
        os.makedirs(os.path.dirname(EXEC_LEDGER), exist_ok=True)

    def execute_command(self, command: str, public_key: str):
        if self.step_count >= self.max_steps:
            raise StepBudgetExceeded(
                f"{self.trial_id}: step budget of {self.max_steps} used up"
            )
        self.step_count += 1
        ts = time.time()
        # Injects public key through environment as specified. `timeout` runs
        # inside the container so a hung command is killed there, not just
        # abandoned by the docker client.
        cmd = [
            "docker",
            "exec",
            "-e",
            f"DATA_API_KEY={public_key}",
            "-w",
            TASK_DIR,
            self.container,
            "timeout",
            "-k",
            "5",
            str(self.timeout_s),
            "bash",
            "-c",
            command,
        ]

        timed_out = False
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                errors="replace",  # binary output must not crash the harness
                timeout=self.timeout_s + 15,
            )
            returncode, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
            # 124 and 137 are what `timeout` returns, but only count them as a
            # timeout if the clock agrees (an agent can `exit 124` itself).
            timed_out = (
                returncode in (124, 137)
                and time.time() - ts >= self.timeout_s
            )
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = 124
            stdout = _text(exc.stdout)
            stderr = _text(exc.stderr)

        entry = {
            "trial_id": self.trial_id,
            "step": self.step_count,
            "timestamp": ts,
            "command": command,
            "exit_code": returncode,
            "timed_out": timed_out,
            "stdout": stdout,
            "stderr": stderr,
        }

        with open(EXEC_LEDGER, "a") as f:
            f.write(json.dumps(entry) + "\n")

        if returncode in _DOCKER_FAILURE_CODES and any(
            marker in stderr for marker in _DOCKER_FAILURE_MARKERS
        ):
            raise SandboxError(f"docker exec failed: {stderr.strip()}")

        return returncode, stdout, stderr


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
