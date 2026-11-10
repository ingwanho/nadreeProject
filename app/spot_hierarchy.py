"""Display a hierarchy node's own name separately from its leaf name."""


def unit_name(row):
    # Do not revive a stale leaf name if the canonical name was cleared.
    return row.get("unit_name") if "unit_name" in row else row.get("spot_name")
