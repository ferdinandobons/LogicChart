from __future__ import annotations

from backend.domain import Order, OrderStatus


def transition(order: Order) -> None:
    """Planted #4: match on order.status with no `case _` default."""
    match order.status:
        case OrderStatus.CART:
            order.status = OrderStatus.PLACED
        case OrderStatus.PLACED:
            order.status = OrderStatus.PAID
        case OrderStatus.PAID:
            order.status = OrderStatus.SHIPPED
        case OrderStatus.SHIPPED:
            order.status = OrderStatus.DELIVERED


def summarize(order: Order) -> dict[str, object]:
    """Planted #10: a no-op branch (the refunded case does nothing)."""
    summary: dict[str, object] = {"id": order.id, "total": order.total_cents}
    if order.status == OrderStatus.REFUNDED:
        pass
    else:
        summary["status"] = order.status.value
    return summary
