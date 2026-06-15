from __future__ import annotations

from backend.domain import ApiError, Order, OrderStatus


def cancel(order: Order) -> None:
    """Refundable set {PLACED, PAID}; rejects with 404 - sibling of request_refund."""
    if order.status not in (OrderStatus.PLACED, OrderStatus.PAID):
        raise ApiError(404, "order is not cancellable")
    do_cancel(order)


def request_refund(order: Order) -> None:
    """Planted #7/#8: a divergent refundable set {PAID, SHIPPED, DELIVERED} and a 409
    where the sibling cancel() rejects the same kind of state with 404."""
    if order.status not in (OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DELIVERED):
        raise ApiError(409, "order is not refundable")
    do_refund(order)


def create(payload: object) -> Order:
    """Control: validates before writing."""
    if not has_items(payload):
        raise ApiError(422, "an order needs at least one item")
    return build_order(payload)


def quick_order(payload: object) -> Order:
    """Planted #13: the validation guard create() has is missing here."""
    return build_order(payload)
