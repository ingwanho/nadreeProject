"""Plan or apply chat deletion for rentals actually returned at least 90 days ago."""
import argparse
import logging
from collections import Counter
from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.chat import FirebaseChat
from app.config import Settings
from app.db import Database
from app.errors import Problem
from app.security import now


logger = logging.getLogger(__name__)
RETENTION = timedelta(days=90)


def eligible(db, cutoff):
    contracts, reservations = db.table("MSP_RENTAL_CONTRACT"), db.table("MSP_RESERVATION")
    return (select(contracts.c.rental_contract_id, contracts.c.reservation_id,
                   reservations.c.uid_token, reservations.c.spot_master_id)
        .join(reservations, contracts.c.reservation_id == reservations.c.reservation_id)
        .where(contracts.c.contract_status == "RETURNED", reservations.c.reservation_status == "RETURNED",
               contracts.c.actual_end_time.is_not(None), contracts.c.actual_end_time <= cutoff,
               contracts.c.uid_token == reservations.c.uid_token,
               contracts.c.pickup_spot_master_id == reservations.c.spot_master_id))


def run(db, chat, *, apply=False, at=None):
    cutoff = (at or now()) - RETENTION
    query = eligible(db, cutoff)
    if not apply:
        with db.engine.connect() as connection:
            count = connection.scalar(select(func.count()).select_from(query.subquery()))
        return {"mode": "plan", "cutoffUtc": cutoff.isoformat(), "eligibleRentals": count}
    if not chat.settings.fcm_chat_enabled:
        raise Problem(503, "CHAT_NOT_CONFIGURED")
    with db.engine.connect() as connection:
        mysql = connection.dialect.name == "mysql"
        name = "nadree:job:chat-retention"
        if mysql and connection.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": name}) != 1:
            return {"mode": "apply", "busy": True}
        try:
            return _apply(db, chat, query, cutoff)
        finally:
            if mysql:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})


def _apply(db, chat, query, cutoff):
    contracts = db.table("MSP_RENTAL_CONTRACT")
    counters = Counter(eligibleRentals=0, deleted=0, alreadyDeleted=0, noRoom=0, changed=0, failed=0)
    last = ""
    while True:
        with db.engine.connect() as connection:
            ids = list(connection.scalars(query.with_only_columns(contracts.c.rental_contract_id)
                .where(contracts.c.rental_contract_id > last).order_by(contracts.c.rental_contract_id).limit(200)))
        if not ids:
            break
        for ident in ids:
            counters["eligibleRentals"] += 1
            try:
                # Recheck the current joined SQL rows under a lock; never delete
                # from a scheduled return date or a stale candidate snapshot.
                with Session(db.engine) as session, session.begin():
                    row = session.execute(query.where(contracts.c.rental_contract_id == ident)
                        .with_for_update()).mappings().first()
                    if row is None:
                        counters["changed"] += 1
                        continue
                    result = chat.store().purge_booking(row["reservation_id"], row["uid_token"], row["spot_master_id"])
                counters[result] += 1
            except Exception as error:
                counters["failed"] += 1
                logger.warning("Chat retention deferred: %s", type(error).__name__)
        last = ids[-1]
    return {"mode": "apply", "cutoffUtc": cutoff.isoformat(), **counters}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Delete eligible chats; default only counts SQL candidates")
    args = parser.parse_args()
    settings = Settings()
    db = Database(settings.database_url.get_secret_value())
    if db.engine is None:
        raise SystemExit("NADREE_DATABASE_URL is required")
    try:
        result = run(db, FirebaseChat(settings), apply=args.apply)
        print(result)
        if result.get("failed"):
            raise SystemExit(1)
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    main()
