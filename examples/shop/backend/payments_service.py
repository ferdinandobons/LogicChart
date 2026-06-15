from __future__ import annotations

from backend.domain import Account, ApiError, Order, PaymentResult

# Planted #11: a guard gated on an always-false module constant (dead guard).
ENABLE_DOUBLE_CHARGE_GUARD = False


def handle_result(result: PaymentResult) -> str:
    """Planted #5: if/elif chain on PaymentResult missing FRAUD_REVIEW and no else."""
    if result == PaymentResult.APPROVED:
        return "paid"
    elif result == PaymentResult.DECLINED:
        return "declined"
    elif result == PaymentResult.PENDING:
        return "pending"


def charge(account: Account, order: Order) -> PaymentResult:
    """Planted #6: broad-except that swallows the failure (and the dead guard #11)."""
    if ENABLE_DOUBLE_CHARGE_GUARD:
        raise ApiError(409, "double charge blocked")
    try:
        result = gateway_charge(account, order)
    except Exception:
        pass
    return result


def refund_payment(order: Order) -> None:
    """Planted #14 (sibling A): logs and alerts on the invalid-amount path."""
    if order.total_cents <= 0:
        log_warning("refund requested for non-positive amount")
        alert_ops("suspicious refund")
        raise ApiError(422, "invalid refund amount")
    gateway_refund(order)


def capture_payment(order: Order) -> None:
    """Planted #14 (sibling B): silently returns on the same invalid-amount path."""
    if order.total_cents <= 0:
        return
    gateway_capture(order)
