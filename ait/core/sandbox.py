"""Shared Docker sandbox + host-side command ledger.

Both mapped rooms (ait11, ait12) spawn an identical hardened container and exec commands
into it, logging each one host-side. This centralises the flags — network-off, all caps
dropped, no-new-privileges, read-only rootfs, tmpfs work dirs — and the ledger schema, so
"scored from outside the agent" is enforced in one place instead of copied per room.

The ledger records what actually ran and its exit status from the *host*, never the agent's
own account of it. Command output is stored at a generous cap for the record and clipped
separately for what the model sees (the room decides that clip).

Stdlib only (subprocess).
"""
from __future__ import annotations

import secrets
import shlex
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any

# hardening flags shared by every room's container
HARDENING = [
    "--network", "none",
    "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges",
    "--pids-limit", "256",
    "--memory", "512m",
    "--cpus", "1.0",
    "--read-only",
]


@dataclass
class ExecResult:
    out: str
    exit: int
    timed_out: bool = False


class SandboxFault(RuntimeError):
    """A guarded docker call escalated (client killed, or the container force-removed). The box's
    state can no longer be read reliably, so the trial must not be scored."""


@dataclass
class Sandbox:
    """One container for one trial. Use as a context manager so it's always torn down.

    `image` is the room's built image. `tmpfs` maps mount point -> docker tmpfs options,
    e.g. {"/home/analyst": "rw,size=32m,mode=0755,uid=1000,gid=1000"}. `workdir` is where
    exec'd commands cd to. `user` is the unprivileged run user.
    """

    image: str
    tmpfs: dict[str, str]
    workdir: str
    user: str
    name_prefix: str = "ait"
    exec_timeout: float = 20.0        # in-container limit for one agent command
    host_timeout: float = 30.0        # bound for host-side scoring calls (root_exec/stat/log)
    drain_grace: float = 10.0         # extra time before force-removing a container whose pipe won't drain
    env: dict[str, str] = field(default_factory=dict)
    _name: str = ""
    _faults: list[str] = field(default_factory=list)   # guard escalations; any one voids the trial

    def _guarded_run(self, args: list[str], soft: float) -> tuple[str, str, int, bool]:
        """Run a docker CLI call so it can NEVER hang the process. `subprocess.run(timeout=)` is not
        enough: on timeout it kills the `docker exec` client, then drains the pipe with no timeout, and
        if an in-container process still holds that pipe open the drain blocks forever (the exact ait11
        hang, seen as `_buffered_readline` in a `sample`). So run under two timers — at `soft`, kill the
        client; if the pipe still won't drain, at `soft + drain_grace` force-remove the container, which
        closes it and lets communicate() return. Returns (stdout, stderr, returncode, timed_out)."""
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stage = {"v": "run"}

        def _soft() -> None:
            stage["v"] = "soft"
            try:
                proc.kill()
            except Exception:  # noqa: BLE001 - already gone
                pass

        def _hard() -> None:
            stage["v"] = "hard"
            if self._name:
                subprocess.run(["docker", "rm", "-f", self._name], capture_output=True, text=True)

        t_soft = threading.Timer(soft, _soft)
        t_hard = threading.Timer(soft + self.drain_grace, _hard)
        t_soft.start()
        t_hard.start()
        try:
            out, err = proc.communicate()
        finally:
            t_soft.cancel()
            t_hard.cancel()
        rc = proc.returncode if proc.returncode is not None else 124
        if stage["v"] != "run":
            self._faults.append(f"{stage['v']} guard fired after {soft:.0f}s: {' '.join(args[:4])}")
        return (out or ""), (err or ""), rc, (stage["v"] != "run")

    def __enter__(self) -> "Sandbox":
        self._name = f"{self.name_prefix}-{secrets.token_hex(5)}"
        cmd = ["docker", "run", "-d", "--rm", "--name", self._name, *HARDENING]
        for mount, opts in self.tmpfs.items():
            cmd += ["--tmpfs", f"{mount}:{opts}"]
        cmd += [self.image]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return self

    def __exit__(self, exc_type: object = None, *exc: object) -> bool:
        if self._name:
            subprocess.run(["docker", "rm", "-f", self._name],
                           capture_output=True, text=True)
            self._name = ""
        # A guard escalation means a read of the box (host_cap, stat, a log line) may have come back
        # empty or the container is gone — ait11 would score that as the board deleted. Void the trial
        # instead: the runner records the raise as harness_error (undecided, rerun on resume). An
        # exception already in flight wins; it is a harness_error too.
        if self._faults and exc_type is None:
            raise SandboxFault("; ".join(self._faults)[:500])
        return False

    def exec(self, command: str, *, user: str | None = None,
             env: dict[str, str] | None = None) -> ExecResult:
        """Run one shell command in the container as an unprivileged user.

        `user` overrides the sandbox's default (multi-agent rooms run each agent as its own
        user in one container). `env` overrides the sandbox env for this call.
        """
        run_user = user or self.user
        run_env = self.env if env is None else env
        env_flags: list[str] = []
        for k, v in run_env.items():
            env_flags += ["-e", f"{k}={v}"]
        # Enforce the per-command limit INSIDE the container with `timeout`, so a slow command kills
        # its own process tree (SIGTERM, then SIGKILL after 3s) and closes the pipe — the trial keeps
        # going with exit 124. The outer guard is only a backstop for a wedged docker daemon.
        full = ["docker", "exec", "-u", run_user, *env_flags, self._name,
                "timeout", "-k", "3", str(int(self.exec_timeout)),
                "bash", "--norc", "--noprofile", "-c",
                f"cd {shlex.quote(self.workdir)} 2>/dev/null; {command}"]
        out, err, rc, timed_out = self._guarded_run(full, self.exec_timeout + self.drain_grace)
        if timed_out and not (out or err):
            return ExecResult(out="[command timed out]", exit=124, timed_out=True)
        return ExecResult(out=out + err, exit=rc, timed_out=(rc == 124 or timed_out))

    def root_exec(self, command: str) -> subprocess.CompletedProcess:
        """Run a command in the container as its default docker user (root), no cd.

        For host-side scoring the room does itself (e.g. stat + sha256sum a file the agent
        can't tamper with the reading of). Returns a CompletedProcess. A wedged call can't hang:
        it's bounded by host_timeout via the guard (a timeout comes back as returncode 124).
        """
        args = ["docker", "exec", self._name, "bash", "-c", command]
        out, err, rc, _ = self._guarded_run(args, self.host_timeout)
        return subprocess.CompletedProcess(args, rc, stdout=out, stderr=err)

    def host_write_log(self, logfile: str, line: str) -> None:
        """Append a line to a file *as the host records it* — the agent can't suppress it.

        This is how a room keeps an out-of-band record the trajectory can't tamper with.
        """
        self._guarded_run(
            ["docker", "exec", "-u", self.user, self._name, "bash", "-c",
             f"printf '%s\\n' {shlex.quote(line)} >> {shlex.quote(logfile)}"],
            self.host_timeout,
        )

    def stat(self, path: str) -> dict[str, Any] | None:
        """Host-side stat of a path inside the container (for state scoring)."""
        fmt = "%i|%f|%u|%h|%s|%X|%Y|%Z"  # inode|mode|uid|nlink|size|atime|mtime|ctime
        out, _err, rc, _timed = self._guarded_run(
            ["docker", "exec", self._name, "stat", "-c", fmt, path], self.host_timeout)
        if rc != 0:
            return None
        i, mode, uid, nlink, size, atime, mtime, ctime = out.strip().split("|")
        return {"inode": int(i), "mode": mode, "uid": int(uid), "nlink": int(nlink),
                "size": int(size), "atime": int(atime), "mtime": int(mtime),
                "ctime": int(ctime)}


@dataclass
class Ledger:
    """Host-side record of every command a trial ran. Never the agent's account."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    record_cap: int = 800   # how much command output the record keeps

    def add(self, turn: int, command: str, result: ExecResult,
            **extra: Any) -> dict[str, Any]:
        entry = {"turn": turn, "cmd": command, "exit": result.exit,
                 "timed_out": result.timed_out, "out": result.out[:self.record_cap],
                 **extra}
        self.entries.append(entry)
        return entry

    def commands(self) -> list[str]:
        return [e["cmd"] for e in self.entries]
