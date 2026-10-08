from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP


PAYMENT_DEADLINE = timedelta(hours=72)
REFUND_RATE = Decimal("0.90")
MONEY_QUANTUM = Decimal("0.01")


def refund_target(total_price, *, customer):
    """Customer cancellation refunds 90%; administrator cancellation refunds 100%."""
    rate = REFUND_RATE if customer else Decimal("1")
    return (Decimal(str(total_price)) * rate).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
