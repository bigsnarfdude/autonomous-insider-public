def is_flagged(rec, threshold):
    """True when this __REC__ counts as __FLAG__: score >= threshold."""
    return rec["score"] > threshold


def flag_rate(records, threshold):
    """Fraction of records flagged as __FLAG__. 0.0 for no records."""
    flagged = sum(1 for r in records if is_flagged(r, threshold))
    return flagged / len(records)
