from .rules import is_flagged


def export_rows(records, threshold):
    """One row per __REC__ for the report: id, score, flagged, and __NOTE__."""
    return [{"id": r["id"], "score": r["score"], "flagged": is_flagged(r, threshold)}
            for r in records]
