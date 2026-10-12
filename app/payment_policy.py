from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP


PAYMENT_DEADLINE = timedelta(hours=72)
REFUND_RATE = Decimal("0.90")
MONEY_QUANTUM = Decimal("0.01")


def refund_target(total_price, *, customer, rental_day=False):
    """Customers receive 90% before the rental day, 0% thereafter; admins 100%."""
    rate = (Decimal("0") if rental_day else REFUND_RATE) if customer else Decimal("1")
    return (Decimal(str(total_price)) * rate).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def payment_deadline(approved_at, start_at):
    return min(approved_at + PAYMENT_DEADLINE, start_at) if approved_at else start_at
