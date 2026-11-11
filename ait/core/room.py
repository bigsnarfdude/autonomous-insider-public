"""The Room interface every AIT room implements.

A room is four things: the arms it offers, how it prepares one trial's world, how it runs
one trial (producing a trial record scored from outside the agent), and how it turns a set
of trial records into metrics. Keeping this tiny is the point — the shared core (provider,
sandbox, ledger, gate, manifest) does the heavy lifting, so a room module is mostly its own
prompts, arm definitions, and scoring rules.

`run_trial` receives a `TrialContext` carrying the pinned provider and the per-trial seed,
so no room reimplements calling the model or seeding.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .provider import Provider


@dataclass
class TrialContext:
    arm: str
    trial: int
    seed: int
    provider: Provider
    image: str
    workdir: str = "/home/analyst/work"
    extra: dict[str, Any] = field(default_factory=dict)


class Room(Protocol):
    """Implemented by each rooms/aitNN module."""

    name: str
    image: str                       # docker image the room's trials run in

    def arms(self) -> list[str]:
        """All arm ids this room can run."""
        ...

    def default_arms(self) -> list[str]:
        """The arms a plain `ait run --room X` runs (a subset, current behaviour)."""
        ...

    def build(self) -> None:
        """Build/prepare the docker image and any fixtures. Idempotent."""
        ...

    def run_trial(self, ctx: TrialContext) -> dict[str, Any]:
        """Run one trial and return its record. Must include `arm`, `trial`, and either
        `decided: bool` or an `end_reason` the gate understands."""
        ...

    def score(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Turn trial records into metrics. Rates go through core.gate so undecided
        trials never count as clean."""
        ...

    # Capability (core/ceiling.py). Every room declares exactly one of:
    #   capability: tuple[Ceiling, ...]   told arms whose success rate is the model's ceiling for
    #                                     each intent metric (the told arm is in default_arms)
    #   capability_exempt: Exempt         why no told arm is needed (prompt-only, or the act is
    #                                     printed verbatim in the task)
    # A room whose unit isn't one trial record (multi-agent, its own void rule) also supplies
    # capability_units(records) -> list of units carrying `arm` and `decided`.
