"""退款计费样例测试。

test_member_discount_not_stacked_with_threshold 在修复前必须失败：
当前实现会在 200 元订单上先打 8 折再满减，得到 150，而规格 R2 要求只取一种优惠（160）。
"""

from refund import Order, compute_refund


def test_member_discount_not_stacked_with_threshold():
    order = Order(paid_amount=200.00, member=True)
    assert compute_refund(order) == 160.00


def test_member_discount_below_threshold():
    order = Order(paid_amount=90.00, member=True)
    assert compute_refund(order) == 72.00


def test_non_member_threshold_discount():
    order = Order(paid_amount=120.00, member=False)
    assert compute_refund(order) == 110.00


def test_refund_never_exceeds_paid_amount():
    order = Order(paid_amount=50.00, member=False)
    assert compute_refund(order) == 50.00
