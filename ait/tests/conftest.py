import json
from pathlib import Path

import pytest


@pytest.fixture
def eee_schema():
    """A vendored copy of evaleval/every_eval_ever's eval.schema.json, fetched 2026-09-28. Fixed
    on purpose: a live fetch would make export tests fail on the coalition's schedule, not ours.
    Re-vendor by hand when core/export_eee.py changes to track a new schema version, and note the
    date in the commit — a validated export can silently stop validating if their schema tightens."""
    return json.loads((Path(__file__).parent / "fixtures" / "eee_eval.schema.json").read_text())
