"""Exact same-model interval assignment; caller holds the spot and vehicle locks."""
from collections import defaultdict
from datetime import datetime, timedelta

from ortools.sat.python import cp_model
from sqlalchemy import update

from app.errors import Problem
from app.pricing import daily_price, load_tiers
from app.rental_common import MOVABLE, day_end, is_open, local_date, rows
from app.security import now


def reservation_end(request, reservation):
    return day_end(request, local_date(request, reservation["end_datetime"]))


def price_key(item, tiers):
    return item["rental"]["price_type"], daily_price(item, tiers)


def reservation_price(reservation, vehicles, tiers):
    criteria = reservation.get("required_criteria_json") or {}
    if not isinstance(criteria, dict):
        raise Problem(409, "RESERVATION_CRITERIA_INVALID")
    if "priceType" in criteria or "dailyPrice" in criteria:
        kind, price = criteria.get("priceType"), criteria.get("dailyPrice")
        if kind not in ("BASIC", "PREMIUM") or type(price) is not int or price < 0:
            raise Problem(409, "RESERVATION_PRICE_INVALID")
        return kind, price
    assigned = vehicles.get(reservation["assigned_vehicle_id"])
    if assigned is None:
        raise Problem(409, "RESERVATION_PRICE_UNAVAILABLE")
    result = price_key(assigned, tiers)
    if result[1] is None:
        raise Problem(409, "PRICE_NOT_CONFIGURED")
    return result


def solve_intervals(jobs, fixed, *, timeout=2.0):
    """jobs: (key, start_us, end_us, candidate_ids, preferred_id)."""
    model = cp_model.CpModel()
    intervals = defaultdict(list)
    choices, changes = {}, []
    for vehicle, start, end in fixed:
        if end > start:
            intervals[vehicle].append(model.new_fixed_size_interval_var(start, end - start, "fixed"))
    for key, start, end, candidates, preferred in jobs:
        if end <= start or not candidates:
            raise Problem(409, "VEHICLE_UNAVAILABLE")
        variables = {}
        for vehicle in sorted(candidates):
            present = model.new_bool_var(f"{key}:{vehicle}")
            intervals[vehicle].append(model.new_optional_fixed_size_interval_var(start, end - start, present, "booking"))
            variables[vehicle] = present
            if vehicle != preferred:
                changes.append(present)
        model.add_exactly_one(variables.values())
        choices[key] = variables
    for group in intervals.values():
        model.add_no_overlap(group)
    model.minimize(sum(changes))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    result = solver.solve(model)
    if result == cp_model.INFEASIBLE:
        raise Problem(409, "VEHICLE_UNAVAILABLE")
    if result not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise Problem(503, "AVAILABILITY_CHECK_TIMEOUT")
    return {key: next(v for v, flag in candidates.items() if solver.value(flag)) for key, candidates in choices.items()}


def compute_assignment(request, session, spot, vehicles, contracts, *, candidate=None, checkout=None,
                       maintenance=None, omit_reservation=None):
    at = now()
    tiers = load_tiers(request, session, spot["spot_master_id"])
    models = {x["rental"]["model_id"] for x in vehicles.values()}
    if len(models) != 1:
        raise Problem(409, "MODEL_ASSIGNMENT_INCONSISTENT")
    t = request.app.state.db.table("MSP_RESERVATION")
    # REQUESTED 예약도 승인 전까지는 선착순 용량을 점유한다. 그렇지 않으면
    # 같은 모델·기간의 동시 요청이 모두 통과한 뒤 승인 순서가 결과를 바꾼다.
    reservations = rows(session, t, t.c.spot_master_id == spot["spot_master_id"],
                        t.c.model_id.in_(models), t.c.reservation_status.in_(("REQUESTED", "APPROVED")))
    reservations = [r for r in reservations if r["reservation_id"] != omit_reservation and reservation_end(request, r) > at]
    if candidate:
        reservations.append(candidate)
    start = min([at] + [r["start_datetime"] for r in reservations])
    end = max([at + timedelta(days=1)] + [reservation_end(request, r) for r in reservations] +
              ([checkout[2]] if checkout else []) + ([maintenance[2]] if maintenance else []))
    origin = datetime(2000, 1, 1)

    def tick(value):
        delta = value - origin
        return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds

    fixed, jobs = [], []
    for ident, item in vehicles.items():
        state, model = item["state"], item["model"]
        active = [c for c in contracts if c["vehicle_id"] == ident and is_open(c)]
        inconsistent = (state is None or model is None or len(active) > 1 or
                        state["status"] == "ON_RENT" and not active or
                        active and state["status"] != "ON_RENT")
        if inconsistent:
            raise Problem(409, "RENTAL_STATE_INCONSISTENT")
        if not item["vehicle"]["is_active"] or not item["rental"]["rental_enabled"] or not model["is_active"] or state["status"] == "DISABLED":
            fixed.append((ident, tick(start), tick(end)))
            continue
        if state["status"] == "MAINTENANCE" and (not maintenance or maintenance[0] != ident):
            if state["maintenance_until"] is None:
                raise Problem(409, "RENTAL_STATE_INCONSISTENT")
            until = day_end(request, state["maintenance_until"])
            if until > at:
                fixed.append((ident, tick(max(start, state["status_changed_at"])), tick(until)))
        for contract in [c for c in contracts if c["vehicle_id"] == ident and c["contract_status"] != "CANCELED"]:
            cs = contract["actual_start_time"]
            ce = contract["actual_end_time"]
            if cs is None or contract["contract_status"] == "RETURNED" and ce is None:
                raise Problem(409, "RENTAL_STATE_INCONSISTENT")
            if ce is None:
                planned = contract["planned_end_date"]
                ce = day_end(request, planned) if planned else end
                if contract["contract_status"] == "OVERDUE" or ce <= at:
                    ce = end
            if cs < end and ce > start:
                fixed.append((ident, tick(max(cs, start)), tick(min(ce, end))))
    for ident, begin, finish in [x for x in (checkout, maintenance) if x]:
        fixed.append((ident, tick(begin), tick(finish)))
    linked = {c["reservation_id"] for c in contracts if c["reservation_id"]}
    for r in reservations:
        if r["reservation_id"] in linked:
            raise Problem(409, "RENTAL_STATE_INCONSISTENT")
        expected = reservation_price(r, vehicles, tiers)
        eligible = [ident for ident, item in vehicles.items() if price_key(item, tiers) == expected]
        if r["vehicle_assignment_status"] == "LOCKED":
            eligible = [ident for ident in eligible if ident == r["assigned_vehicle_id"]]
        elif r["vehicle_assignment_status"] not in MOVABLE + ("SOFT_HOLD",):
            raise Problem(409, "RESERVATION_ASSIGNMENT_INVALID")
        jobs.append((r["reservation_id"], tick(r["start_datetime"]), tick(reservation_end(request, r)), eligible, r["assigned_vehicle_id"]))
    assignments = solve_intervals(jobs, fixed, timeout=request.app.state.settings.availability_timeout_seconds)
    return assignments, {r["reservation_id"]: r for r in reservations}


def reservation_history(request, session, previous, values, event, actor_id, reason=None):
    new = {**previous, **values}
    h = request.app.state.db.table("MSP_RESERVATION_HISTORY")
    session.execute(h.insert().values(reservation_id=previous["reservation_id"], event_type=event,
        previous_reservation_status=previous["reservation_status"], new_reservation_status=new["reservation_status"],
        previous_vehicle_id=previous["assigned_vehicle_id"], new_vehicle_id=new["assigned_vehicle_id"],
        previous_assignment_status=previous["vehicle_assignment_status"], new_assignment_status=new["vehicle_assignment_status"],
        reason=reason, changed_by=actor_id, created_at=now()))


def apply_assignments(request, session, assignments, reservations, actor_id, *, skip=None):
    table = request.app.state.db.table("MSP_RESERVATION")
    for ident, vehicle_id in assignments.items():
        previous = reservations[ident]
        if ident == skip or previous["assigned_vehicle_id"] == vehicle_id:
            continue
        values = dict(assigned_vehicle_id=vehicle_id, vehicle_assignment_status="REALLOCATED", vehicle_assigned_at=now(), updated_at=now())
        result = session.execute(update(table).where(table.c.reservation_id == ident,
            table.c.reservation_status == "APPROVED", table.c.vehicle_assignment_status.in_(MOVABLE)).values(**values))
        if result.rowcount != 1:
            raise Problem(409, "RESERVATION_CHANGED")
        reservation_history(request, session, previous, values, "VEHICLE_REASSIGNED", actor_id)
