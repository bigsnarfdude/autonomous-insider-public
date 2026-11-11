"""Structured room metadata: the benchmark card and the metric registry.

One source of truth for what a room measures and how to read its numbers. Today that lives in
three places (the catalog HTML, the room docstring, the README row) and drifts; a room that
declares `card` and `metrics` can have all three rendered from it, and can be exported to other
reporting formats (Every Eval Ever / Evaluation Cards, see core/export_eee.py) without losing
what makes its numbers trustworthy.

Field names follow the Auto-BenchmarkCard sections Evaluation Cards scores completeness against
(benchmark details, purpose, data, methodology, ethics, risks), so an export is a rename, not a
rewrite. Where a room genuinely has no value — no human subjects, no dataset — say so in the field
rather than leaving it blank: an empty field reads as "not reported", an explicit "not applicable"
reads as a decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Source = Literal["exact", "regex", "judge"]


@dataclass(frozen=True)
class MetricSpec:
    """How to read one of a room's metrics."""

    id: str
    lower_is_better: bool                 # for a safety room: is a higher rate worse?
    source: Source                        # exact = host-side ground truth; regex = text match; judge = LLM label
    name: str = ""                        # display name; defaults to id
    definition: str = ""                  # one sentence: what a hit is
    kind: str = "rate"                    # rate (hits/decided) | count | levels
    unit: str = "proportion"
    headline: bool = True                 # False = diagnostic only (e.g. a regex over the reasoning)


@dataclass(frozen=True)
class RoomCard:
    """A room's benchmark card. Every field is plain text or a list of plain text."""

    # benchmark details
    name: str
    overview: str
    data_type: str = "text (agentic, multi-turn)"
    domains: tuple[str, ...] = ("AI safety", "agent security")
    languages: tuple[str, ...] = ("English",)
    similar_benchmarks: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    field_anchor: str = ""                # the public incident or report the room reproduces
    # purpose & intended users
    goal: str = ""
    construct: str = ""                   # the one question the room asks
    audience: tuple[str, ...] = ("safety evaluators", "agent deployers", "security teams")
    tasks: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    out_of_scope_uses: tuple[str, ...] = ()
    # data
    data_source: str = ""
    data_size: str = ""
    data_format: str = ""
    annotation: str = ""
    # methodology
    methods: tuple[str, ...] = ()
    calculation: str = ""
    interpretation: str = ""
    baseline_results: str = ""
    validation: tuple[str, ...] = ()
    # ethical & legal
    privacy: str = "No personal data. All names, values and services in the scenario are synthetic."
    data_licensing: str = ""
    consent: str = "Not applicable: no human subjects."
    compliance: str = "Not applicable: no human subjects."
    # risks
    risks: tuple[str, ...] = ()
    contamination: str = ""
    arms: dict[str, str] = field(default_factory=dict)     # arm id -> what varies


REQUIRED = ("name", "overview", "goal", "construct", "tasks", "limitations", "out_of_scope_uses",
            "data_source", "data_size", "data_format", "methods", "calculation", "interpretation",
            "baseline_results", "validation", "risks", "contamination", "arms", "data_licensing")


def missing_fields(card: RoomCard) -> list[str]:
    """Fields a card leaves empty. A complete card returns []."""
    return [f for f in REQUIRED if not getattr(card, f)]
