"""Per-run manifest: everything needed to say what produced a set of outputs.

No room recorded this, which is why a stored output file couldn't be traced to its code,
prompt, image, or provider. A manifest is written once per run and pins:
 - the git commit + dirty flag of the repo,
 - a content hash of the room module and its prompt/rubric assets,
 - the Docker image id actually used,
 - the provider config (model, pin, sampling, seed base),
 - the CLI invocation and wall-clock window.

Reproducibility is then a diff of two manifests.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


def _run(cmd: list[str]) -> str | None:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def git_state(repo: Path) -> dict[str, Any]:
    """`dirty` = tracked files differ from the commit, i.e. the code that ran isn't the commit.
    Untracked files are listed, not counted as dirty: a stray report in the tree marked every run
    dirty and made the flag meaningless."""
    commit = _run(["git", "-C", str(repo), "rev-parse", "HEAD"])
    status = _run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"])
    untracked = _run(["git", "-C", str(repo), "ls-files", "--others", "--exclude-standard"])
    branch = _run(["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"])
    return {"commit": commit, "branch": branch,
            "dirty": bool(status) if status is not None else None,
            "untracked": untracked.splitlines() if untracked else []}


def hash_paths(paths: list[Path]) -> str:
    """Stable content hash over a set of files (sorted, path + bytes)."""
    h = hashlib.sha256()
    for p in sorted(paths):
        if p.is_file():
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def docker_image_id(image: str) -> str | None:
    return _run(["docker", "image", "inspect", "-f", "{{.Id}}", image])


@dataclass
class Manifest:
    room: str
    model: str
    provider_config: dict[str, Any]
    seed_base: int
    n: int
    arms: list[str]
    repo_git: dict[str, Any] = field(default_factory=dict)
    room_assets_hash: str | None = None
    image: str | None = None
    image_id: str | None = None
    argv: list[str] = field(default_factory=lambda: list(sys.argv))
    python: str = field(default_factory=lambda: sys.version.split()[0])
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    # each `--resume` of this run: when, from which commit, with what command. A run continued on
    # different code is visible here, not silently mixed.
    resumed: list[dict[str, Any]] = field(default_factory=list)
    schema_version: int = 1

    def finish(self) -> "Manifest":
        self.ended_at = time.time()
        return self

    def write(self, path: Path) -> Path:
        path.write_text(json.dumps(asdict(self), indent=2, default=str))
        return path

    @staticmethod
    def diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
        """Fields that differ between two manifests — what makes two runs incomparable."""
        keys = {"room", "model", "provider_config", "seed_base", "arms",
                "room_assets_hash", "image_id"}
        out: dict[str, tuple[Any, Any]] = {}
        for k in keys:
            if a.get(k) != b.get(k):
                out[k] = (a.get(k), b.get(k))
        gc_a = (a.get("repo_git") or {}).get("commit")
        gc_b = (b.get("repo_git") or {}).get("commit")
        if gc_a != gc_b:
            out["commit"] = (gc_a, gc_b)
        return out
