"""Spot routing is mutable; a payment's seller identity is immutable."""
from sqlalchemy import select

from app.errors import Problem


def spot_merchant(db, session, spot_id, environment):
    table = db.table("MSP_SPOT_RENT")
    if not {"paypal_merchant_id", "paypal_environment"}.issubset(table.c.keys()):
        raise Problem(503, "PAYPAL_MERCHANT_SCHEMA_UPDATE_REQUIRED")
    row = session.execute(select(table).where(table.c.spot_master_id == spot_id)
                          .with_for_update()).mappings().first()
    if not row or not row["paypal_merchant_id"]:
        raise Problem(409, "SHOP_PAYPAL_MERCHANT_REQUIRED")
    if row["paypal_environment"] != environment:
        raise Problem(409, "SHOP_PAYPAL_ENVIRONMENT_MISMATCH")
    return row["paypal_merchant_id"]


def payment_client(client, payment):
    if not payment.get("paypal_merchant_id"):
        raise Problem(409, "PAYMENT_MERCHANT_RECONCILIATION_REQUIRED")
    if payment["payment_environment"] != client.settings.paypal_environment:
        raise Problem(409, "PAYMENT_ENVIRONMENT_MISMATCH")
    return client.for_merchant(payment["paypal_merchant_id"])
