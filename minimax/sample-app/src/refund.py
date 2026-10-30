"""退款计费样例：当前实现故意违反规格 R2（会员折扣与满减被叠加）。"""

from dataclasses import dataclass

MEMBER_DISCOUNT_FACTOR = 0.80
THRESHOLD_AMOUNT = 100.00
THRESHOLD_DISCOUNT = 10.00


@dataclass(frozen=True)
class Order:
    paid_amount: float
    member: bool
    shipped: bool = False


def _member_price(paid_amount: float) -> float:
    return round(paid_amount * MEMBER_DISCOUNT_FACTOR, 2)


def _threshold_price(paid_amount: float) -> float:
    if paid_amount < THRESHOLD_AMOUNT:
        return paid_amount
    return round(paid_amount - THRESHOLD_DISCOUNT, 2)


def compute_refund(order: Order) -> float:
    """按规格计算应退金额。"""
    amount = order.paid_amount
    if order.member:
        amount = min(amount, _member_price(amount))
    amount = _threshold_price(amount)
    return round(min(amount, order.paid_amount), 2)
