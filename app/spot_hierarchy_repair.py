"""Build a conservative hierarchy repair plan from an in-memory snapshot.

This module performs no I/O.  Callers must back up, lock, compare each complete
``before`` row and apply the entire plan in one transaction.  A diagnostic makes
the whole plan unusable: no partial operations are returned.  Diagnostic values
contain identifiers only; full before/after rows belong in private artifacts.
"""

from copy import deepcopy
import re
from uuid import NAMESPACE_URL, uuid5


LEVELS = ("org", "region", "local", "spot")
MASTER = "MSP_SPOT_MASTER"
SCOPE = "MSP_ADMIN_SPOT_SCOPE"
NORMAL = {level: "MSP_" + level.upper() for level in LEVELS}
KEYS = {MASTER: "spot_master_id", **{table: level + "_id" for level, table in NORMAL.items()}}
PROFILE = ("address", "zip_code", "biz_reg_num", "phone", "lat", "lng",
           "contract_start", "contract_end", "created_at")


def _present(value):
    return value is not None and value != ""


def _fold(value):
    return value.casefold() if isinstance(value, str) else value


def _name(row):
    # An intentionally cleared current name must not restore an older normal
    # table's name (for example after account/privacy cleanup).
    return row.get("unit_name")


class _Planner:
    def __init__(self, snapshot):
        self.rows = deepcopy(snapshot)
        self.problems = []
        self.original = {}
        self.index = {}
        self.scope_key = None
        for table in (*KEYS, SCOPE):
            if not isinstance(self.rows.get(table), list):
                self.problem("MISSING_OR_INVALID_TABLE", table)
                self.rows[table] = []
        if self.problems:
            return
        for table, key in KEYS.items():
            self.index[table] = {}
            folded_ids, folded_codes = set(), set()
            for row in self.rows[table]:
                if not isinstance(row, dict) or not _present(row.get(key)):
                    self.problem("MISSING_PRIMARY_KEY", table)
                    continue
                ident = row[key]
                if _fold(ident) in folded_ids:
                    self.problem("DUPLICATE_PRIMARY_KEY", table, ident)
                folded_ids.add(_fold(ident))
                self.index[table][ident] = row
                self.original[(table, ident)] = deepcopy(row)
                code = row.get("unit_code")
                if not isinstance(code, str) or not code:
                    self.problem("MISSING_UNIT_CODE", table, ident)
                elif _fold(code) in folded_codes:
                    self.problem("DUPLICATE_UNIT_CODE", table, ident)
                else:
                    folded_codes.add(_fold(code))
        # Only updated scope rows need a usable primary key.  Legacy/orphan
        # scopes are deliberately outside the repair and remain byte-for-byte.
        scope_rows = self.rows[SCOPE]
        for candidate in ("id", "scope_id"):
            if scope_rows and all(candidate in row for row in scope_rows):
                self.scope_key = candidate
                break
        if self.scope_key:
            seen = set()
            for row in scope_rows:
                ident = row[self.scope_key]
                if ident in seen:
                    self.problem("DUPLICATE_PRIMARY_KEY", SCOPE, ident)
                seen.add(ident)
                self.original[(SCOPE, ident)] = deepcopy(row)
        self.master_columns = set().union(*(row.keys() for row in self.rows[MASTER])) if self.rows[MASTER] else set()

    def problem(self, code, table, ident=None):
        item = {"code": code, "table": table}
        if ident is not None:
            item["id"] = ident
        if item not in self.problems:
            self.problems.append(item)

    def normal(self, level, ident, owner=None):
        result = self.index[NORMAL[level]].get(ident)
        if result is None:
            self.problem("MISSING_NORMAL_MAPPING", NORMAL[level], ident)
        elif owner is not None:
            if result.get("contract_id") != owner.get("contract_id"):
                self.problem("CONTRACT_MISMATCH", NORMAL[level], ident)
            for ancestor in LEVELS[:LEVELS.index(level)]:
                key = ancestor + "_id"
                if result.get(key) != owner.get(key):
                    self.problem("ANCESTOR_MISMATCH", NORMAL[level], ident)
        return result

    def masters_by_level(self):
        result = {level: {} for level in LEVELS}
        for row in self.rows[MASTER]:
            level = row.get("hierarchy_level")
            if level not in LEVELS:
                continue
            ident = row.get(level + "_id")
            if not _present(ident):
                self.problem("MISSING_OWN_NORMAL_KEY", MASTER, row["spot_master_id"])
            elif ident in result[level]:
                self.problem("AMBIGUOUS_LEVEL_MASTER", MASTER, row["spot_master_id"])
            else:
                result[level][ident] = row
        return result

    def infer_levels(self):
        for row in self.rows[MASTER]:
            if not _present(row.get("hierarchy_level")):
                level = next((level for level in reversed(LEVELS) if _present(row.get(level + "_id"))), None)
                if level is None:
                    self.problem("CANNOT_INFER_LEVEL", MASTER, row["spot_master_id"])
                else:
                    row["hierarchy_level"] = level
            elif row["hierarchy_level"] not in (*LEVELS, "team", "agency"):
                self.problem("UNSUPPORTED_LEVEL", MASTER, row["spot_master_id"])

    def add_row(self, table, row):
        key = KEYS[table]
        ident = row[key]
        if any(_fold(current[key]) == _fold(ident) for current in self.rows[table]):
            self.problem("GENERATED_ID_COLLISION", table, ident)
            return
        if any(_fold(current.get("unit_code")) == _fold(row.get("unit_code")) for current in self.rows[table]):
            self.problem("GENERATED_CODE_COLLISION", table, ident)
            return
        self.rows[table].append(row)
        self.index[table][ident] = row

    def generated_id(self, label, normal_id):
        ident = str(uuid5(NAMESPACE_URL, "nadree:spot-hierarchy-repair:" + label + ":" + str(normal_id)))
        all_normal_ids = {_fold(row[KEYS[table]]) for table in NORMAL.values() for row in self.rows[table]}
        if _fold(ident) in all_normal_ids:
            self.problem("GENERATED_ID_COLLISION", MASTER, ident)
        return ident

    def backfill_ancestors(self):
        by_level = self.masters_by_level()
        needed = {level: set() for level in LEVELS}
        # Only references reachable from existing masters are in scope.  A
        # retired, unreferenced normal row must not regain a master/permissions.
        for row in self.rows[MASTER]:
            for level in LEVELS:
                ident = row.get(level + "_id")
                if _present(ident):
                    needed[level].add(ident)
                    self.normal(level, ident, row)
        for level in reversed(LEVELS):
            for ident in sorted(needed[level], key=str):
                normal = self.index[NORMAL[level]].get(ident)
                if normal is None:
                    continue
                for ancestor in LEVELS[:LEVELS.index(level)]:
                    ancestor_id = normal.get(ancestor + "_id")
                    if _present(ancestor_id):
                        needed[ancestor].add(ancestor_id)
                        self.normal(ancestor, ancestor_id, normal)
        for level in LEVELS[:-1]:
            for ident in sorted(needed[level], key=str):
                if ident in by_level[level]:
                    continue
                normal = self.index[NORMAL[level]].get(ident)
                if normal is None:
                    continue
                master_id = self.generated_id(level + ":" + str(normal.get("contract_id")), ident)
                name = normal.get(level + "_name")
                values = {"spot_master_id": master_id, "contract_id": normal.get("contract_id"),
                          "hierarchy_level": level, "unit_code": normal.get("unit_code"),
                          "spot_name": None, "unit_name": name, "is_active": normal.get("is_active", 1)}
                for current in LEVELS:
                    key = current + "_id"
                    values[key] = normal.get(key) if LEVELS.index(current) <= LEVELS.index(level) else None
                for field in PROFILE:
                    if field in normal:
                        values[field] = normal[field]
                values.update(org_name=None, region_name=None, local_name=None)
                if self.master_columns:
                    values = {key: value for key, value in values.items() if key in self.master_columns}
                self.add_row(MASTER, values)
                by_level[level][ident] = values

    def convert_direct_spots(self):
        candidates = [row for row in self.rows[MASTER] if row.get("hierarchy_level") == "spot"
                      and not _present(row.get("region_id")) and not _present(row.get("local_id"))]
        for row in sorted(candidates, key=lambda current: (current["unit_code"], str(current["spot_master_id"]))):
            ident, old_code = row["spot_master_id"], row["unit_code"]
            old_normal = self.normal("spot", row.get("spot_id"), row)
            if old_normal is None:
                continue
            parent_code = old_code.rsplit("-", 1)[0] if "-" in old_code else None
            parents = [current for current in self.rows[MASTER]
                       if current.get("unit_code") == parent_code and current.get("hierarchy_level") == "org"
                       and current.get("org_id") == row.get("org_id")
                       and current.get("contract_id") == row.get("contract_id")]
            if len(parents) != 1:
                self.problem("MISSING_OR_AMBIGUOUS_PARENT", MASTER, ident)
                continue
            if any(current is not row and current.get("contract_id") == row.get("contract_id")
                   and current.get("org_id") == row.get("org_id")
                   and current.get("unit_code", "").startswith(old_code + "-") for current in self.rows[MASTER]):
                self.problem("CONVERSION_HAS_DESCENDANTS", MASTER, ident)
                continue
            if sum(current.get("spot_id") == row.get("spot_id") for current in self.rows[MASTER]) != 1:
                self.problem("SHARED_NORMAL_SPOT", MASTER, ident)
                continue
            if old_normal.get("unit_code") != old_code:
                self.problem("NORMAL_CODE_MISMATCH", NORMAL["spot"], row["spot_id"])
                continue
            pattern = re.compile(re.escape(parent_code) + r"-R(\d+)$", re.IGNORECASE)
            reserved = [current.get("unit_code", "") for current in self.rows[MASTER] + self.rows[NORMAL["region"]]]
            sequence = max([int(match.group(1)) for code in reserved if (match := pattern.fullmatch(code))] + [0]) + 1
            code = parent_code + f"-R{sequence:02d}"
            region_id = ident
            if any(_fold(current["region_id"]) == _fold(region_id) for current in self.rows[NORMAL["region"]]):
                region_id = self.generated_id("converted-region", ident)
            normal = {"region_id": region_id, "contract_id": row.get("contract_id"),
                      "org_id": row.get("org_id"), "region_name": _name(row),
                      "unit_code": code, "is_active": row.get("is_active", 1)}
            for field in PROFILE:
                if field in row:
                    normal[field] = row[field]
            self.add_row(NORMAL["region"], normal)
            row.update(hierarchy_level="region", unit_code=code, region_id=region_id,
                       region_name=_name(row), local_id=None, local_name=None, spot_id=None,
                       spot_name=None)
            old_normal["is_active"] = 0
            for scope in self.rows[SCOPE]:
                if scope.get("spot_master_id") == ident and scope.get("unit_code") == old_code:
                    if not self.scope_key or not _present(scope.get(self.scope_key)):
                        self.problem("SCOPE_PRIMARY_KEY_REQUIRED", SCOPE)
                    else:
                        scope["unit_code"] = code

    def validate_final(self):
        self.masters_by_level()
        for row in self.rows[MASTER]:
            ident, level = row["spot_master_id"], row.get("hierarchy_level")
            for referenced_level in LEVELS:
                reference = row.get(referenced_level + "_id")
                if _present(reference):
                    self.normal(referenced_level, reference, row)
            if level not in LEVELS:
                # Existing legacy teams/agencies are not converted or made
                # structural parents by this data repair.
                continue
            number = LEVELS.index(level)
            for position, current in enumerate(LEVELS):
                present = _present(row.get(current + "_id"))
                if (position <= number) != present:
                    self.problem("INVALID_LEVEL_KEYS", MASTER, ident)
            own_normal = self.index[NORMAL[level]].get(row.get(level + "_id"))
            if own_normal and own_normal.get("unit_code") != row.get("unit_code"):
                self.problem("NORMAL_CODE_MISMATCH", MASTER, ident)
            if level == "org":
                continue
            parent_code = row["unit_code"].rsplit("-", 1)[0] if "-" in row["unit_code"] else None
            parents = [current for current in self.rows[MASTER]
                       if current.get("unit_code") == parent_code
                       and current.get("contract_id") == row.get("contract_id")
                       and current.get("org_id") == row.get("org_id")]
            if len(parents) != 1:
                self.problem("MISSING_OR_AMBIGUOUS_PARENT", MASTER, ident)
                continue
            parent = parents[0]
            if parent.get("hierarchy_level") != LEVELS[number - 1]:
                self.problem("INVALID_PARENT_LEVEL", MASTER, ident)
            for ancestor in LEVELS[:number]:
                if row.get(ancestor + "_id") != parent.get(ancestor + "_id"):
                    self.problem("PARENT_ANCESTOR_MISMATCH", MASTER, ident)

    def fill_caches(self):
        by_level = self.masters_by_level()
        # unit_name is the current master unit's authoritative name.  The
        # normalized own-name and the master's name caches must agree without
        # reviving an older normalized value after anonymization.
        for level in LEVELS:
            for ident, row in by_level[level].items():
                normal = self.index[NORMAL[level]].get(ident)
                if normal is not None:
                    normal[level + "_name"] = _name(row)
        for row in self.rows[MASTER]:
            for level in LEVELS[:-1]:
                key, name_key = level + "_id", level + "_name"
                ident = row.get(key)
                if not _present(ident):
                    value = None
                elif ident in by_level[level]:
                    value = _name(by_level[level][ident])
                else:
                    normal = self.index[NORMAL[level]].get(ident)
                    value = normal.get(name_key) if normal is not None else None
                # Do not invent optional columns on an older shared schema.
                if name_key in row or name_key in self.master_columns:
                    row[name_key] = value
            if "spot_name" in row or "spot_name" in self.master_columns:
                if _present(row.get("spot_id")):
                    normal = self.index[NORMAL["spot"]].get(row["spot_id"])
                    row["spot_name"] = normal.get("spot_name") if normal is not None else None
                else:
                    row["spot_name"] = None

    def operations(self):
        result = []
        for table in (*KEYS, SCOPE):
            key = self.scope_key if table == SCOPE else KEYS[table]
            if key is None:
                continue
            for row in self.rows[table]:
                ident = row[key]
                before = self.original.get((table, ident))
                values = deepcopy(row) if before is None else {
                    field: deepcopy(value) for field, value in row.items()
                    if field not in before or before[field] != value}
                if values:
                    result.append({"table": table, "key": {key: ident},
                                   "before": deepcopy(before), "values": values})
        def order(operation):
            table = operation["table"]
            if operation["before"] is None and table != MASTER:
                priority = 0
            elif operation["before"] is None:
                priority = 1 + LEVELS.index(operation["values"]["hierarchy_level"])
            else:
                priority = {MASTER: 5, SCOPE: 7}.get(table, 6)
            return priority, table, str(next(iter(operation["key"].values())))
        return sorted(result, key=order)


def plan_repair(snapshot):
    """Return ``(operations, problems)`` without modifying ``snapshot``.

    Supported changes are narrow: infer a legacy master's missing level, add
    referenced org/region/local masters, reclassify childless direct-org spots,
    and refresh derived name caches.  No rental, account or permission row is
    created.  Existing rows have one merged operation and a complete original
    ``before`` copy, including any database-managed timestamp columns.
    """
    if not isinstance(snapshot, dict):
        return [], [{"code": "INVALID_SNAPSHOT", "table": MASTER}]
    planner = _Planner(snapshot)
    if not planner.problems:
        planner.infer_levels()
        planner.backfill_ancestors()
    if not planner.problems:
        planner.convert_direct_spots()
        planner.validate_final()
    if not planner.problems:
        planner.fill_caches()
    return ([], planner.problems) if planner.problems else (planner.operations(), [])
