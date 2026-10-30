"""退款计费样例：按规格 R2 只取一种优惠（会员折扣与满减不叠加，取较小值）。"""

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
    """按规格计算应退金额：比较会员折扣与满减各自算出的金额并取较小值（R2），且不超过实付金额（R1）。"""
    candidates = [order.paid_amount]
    if order.member:
        candidates.append(_member_price(order.paid_amount))
    candidates.append(_threshold_price(order.paid_amount))
    return round(min(candidates), 2)
