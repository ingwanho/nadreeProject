from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP


PAYMENT_DEADLINE = timedelta(hours=72)
REFUND_RATE = Decimal("0.90")
MONEY_QUANTUM = Decimal("0.01")


def refund_target(total_price, *, rental_day):
    """Return the policy refund target for a captured payment."""
    if rental_day:
        return Decimal("0.00")
    return (Decimal(str(total_price)) * REFUND_RATE).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
