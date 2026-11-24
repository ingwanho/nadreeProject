"""Display a hierarchy node's own name separately from its leaf name."""
from sqlalchemy import and_, exists, func, or_, select


def active_predicate(table):
    parent = table.alias("inactive_parent")
    inside = or_(table.c.spot_master_id == parent.c.spot_master_id,
                 func.substr(table.c.unit_code, 1, func.length(parent.c.unit_code) + 1) == parent.c.unit_code + "-")
    return and_(table.c.is_active == 1, ~exists(select(1).select_from(parent).where(
        parent.c.contract_id == table.c.contract_id, parent.c.org_id == table.c.org_id,
        parent.c.is_active == 0, inside)))


def unit_name(row):
    # Do not revive a stale leaf name if the canonical name was cleared.
    return row.get("unit_name") if "unit_name" in row else row.get("spot_name")
