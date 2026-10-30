# 代码与测试：修改前后快照、差异、推演与日志

本文件汇总 `task-001` 的代码修改证据。所有内容与仓库中的快照文件、
补丁文件、运行日志逐字对应，可用 `sha256sum` 核对。

---

## 1. 修改前后快照

| 阶段 | 文件 | 说明 |
| --- | --- | --- |
| 修改前 | `minimax/sample-app/src/refund.py` | 只读基线，故意违反规格 R2 |
| 修改后 | `minimax/after/src/refund.py` | v2 规格对应的修复结果（规格 v3 对应 `minimax/after-v3/src/refund.py`） |
| 实际运行 | `minimax/work/app/src/refund.py` | 由补丁应用到基线副本产生，内容与 `after/` 一致 |

### 1.1 修改前（基线）

```python
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
```

问题：`_member_price` 先把 200 元打成 160 元，**然后**用打折后的 160 元去判断满减门槛，
160 ≥ 100 仍然减 10 元 → 150 元。两种优惠被叠加，违反 R2。

### 1.2 修改后（v2 规格）

```python
"""退款计费样例：按规格 R2 只取一种优惠（会员折扣与满减不叠加）。"""

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
    """按规格计算应退金额：会员折扣与满减只取对用户更有利的一种（R2），且不超过实付金额（R1）。"""
    candidates = [order.paid_amount]
    if order.member:
        candidates.append(_member_price(order.paid_amount))
    candidates.append(_threshold_price(order.paid_amount))
    return round(min(candidates), 2)
```

要点：两种优惠各自基于**原实付金额**计算，得到候选集合后取最小值 —— 结构上不可能叠加；
实付金额本身也在候选里，因此天然满足 R1 的退款上限。

---

## 2. 代码差异（MiniMax 生成的 unified diff）

补丁文件：`minimax/patches/task-001-7e523a1efb31a008.patch`
sha256：`5ed18f44f0ed2b0ee6406816e6b4845edcacbd7c7a8829a53cfe2e3a4eb5370a`
对应上下文摘要：`7e523a1efb31a0084147dd83eb39167f535f4eb502fd9e32a31ffcd352508d1f`

```diff
--- a/src/refund.py
+++ b/src/refund.py
@@ -1,4 +1,4 @@
-"""退款计费样例：当前实现故意违反规格 R2（会员折扣与满减被叠加）。"""
+"""退款计费样例：按规格 R2 只取一种优惠（会员折扣与满减不叠加）。"""

 from dataclasses import dataclass

@@ -25,9 +25,9 @@


 def compute_refund(order: Order) -> float:
-    """按规格计算应退金额。"""
-    amount = order.paid_amount
+    """按规格计算应退金额：会员折扣与满减只取对用户更有利的一种（R2），且不超过实付金额（R1）。"""
+    candidates = [order.paid_amount]
     if order.member:
-        amount = min(amount, _member_price(amount))
-    amount = _threshold_price(amount)
-    return round(min(amount, order.paid_amount), 2)
+        candidates.append(_member_price(order.paid_amount))
+    candidates.append(_threshold_price(order.paid_amount))
+    return round(min(candidates), 2)
```

规格升级到 v3 后的补丁（`patches/task-001-59dc8d702481b566.patch`，
sha256 `d9d25847887f2a046b0774df654d224163a7b92ca8c40664de193ac3efd370bc`）
逻辑相同，仅按 v3 措辞调整了 docstring：

```diff
-    """按规格计算应退金额。"""
+    """按规格计算应退金额：比较会员折扣与满减各自算出的金额并取较小值（R2），且不超过实付金额（R1）。"""
```

补丁只触碰 `src/refund.py`：**测试文件、规格文件、任务定义均未被修改**，
测试集在修改前后完全一致。

---

## 3. 逐用例推演

规格 v2 的 R2：两种优惠都满足时，只取对用户更有利的一种；R1：不超过实付金额。

| 用例 | 输入 | 修改前结果 | 修改后结果 | 期望 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `test_member_discount_not_stacked_with_threshold` | 200 元，会员 | 200→160→150 | min(200, 160, 190) = **160** | 160 | 目标用例：改前违反 R2，改后只取会员折扣 |
| `test_member_discount_below_threshold` | 90 元，会员 | 90→72→72 | min(90, 72, 90) = **72** | 72 | 回归：未达门槛，仍按 8 折 |
| `test_non_member_threshold_discount` | 120 元，非会员 | 120→110 | min(120, 110) = **110** | 110 | 回归：非会员仅满减 |
| `test_refund_never_exceeds_paid_amount` | 50 元，非会员 | 50→50 | min(50, 50) = **50** | 50 | 回归：R1 上限 |

---

## 4. 测试日志

命令（在 `minimax/` 下执行）：

```bash
bash run.sh test
```

内部实际执行两条等价命令（`sddsync/cli.py` 的 `run_pytest`）：

```bash
cd sample-app && python -m pytest tests -q     # 修改前
cd work/app  && python -m pytest tests -q     # 修改后
```

### 4.1 修改前（`minimax/logs/tests-before.txt`）

```
F...                                                                     [100%]
=================================== FAILURES ===================================
_______________ test_member_discount_not_stacked_with_threshold ________________

    def test_member_discount_not_stacked_with_threshold():
        order = Order(paid_amount=200.00, member=True)
>       assert compute_refund(order) == 160.00
E       assert 150.0 == 160.0
E        +  where 150.0 = compute_refund(Order(paid_amount=200.0, member=True, shipped=False))

tests/test_refund.py:12: AssertionError
=========================== short test summary info ============================
FAILED tests/test_refund.py::test_member_discount_not_stacked_with_threshold
1 failed, 3 passed in 0.02s
```

退出码 `1`；失败类型 `AssertionError`（目标行为未实现），不是环境错误。

### 4.2 修改后（`minimax/logs/tests-after.txt`）

```
....                                                                     [100%]
4 passed in 0.01s
```

退出码 `0`；目标用例与 3 个回归用例全部通过。

### 4.3 机器可读结果（`minimax/work/test-report.json`）

```json
{
  "before": {
    "exit_code": 1,
    "target_failed_with_assertion": true
  },
  "after": {
    "exit_code": 0,
    "all_passed": true
  },
  "target_test": "test_member_discount_not_stacked_with_threshold",
  "ts": "2026-10-30T20:16:55+0800"
}
```

### 4.4 代码版本对应关系

| 运行 | 代码版本 | sha256 | 退出码 | 结果 |
| --- | --- | --- | --- | --- |
| 修改前 | `sample-app/src/refund.py` | `80d1d3100ed339df5e5799daee35ba6684807bdc833edf46c2e1929954c3a4a0` | 1 | 1 failed, 3 passed |
| 修改后 | `work/app/src/refund.py`（= `after/src/refund.py`） | 由补丁 `5ed18f44…` 应用得到 | 0 | 4 passed |

---

## 5. 新增功能测试与回归测试

本次任务**未新增测试文件**：题面要求"同一组目标功能测试在修改前失败、修改后通过"，
因此目标测试与回归测试来自业务工程原有测试集 `sample-app/tests/test_refund.py`（4 个用例）。
补充检查只覆盖题面已声明的行为：

| 补充检查 | 位置 | 覆盖的已声明行为 |
| --- | --- | --- |
| 上下文必须包含 R2 / `compute_refund` / 目标用例 id | `sddsync/context.py` 的 `required_context_tokens` 校验 | 上下文正确 |
| 符号必须带真实行号 | `sddsync/context.py` 的 `extract_symbols`（`ast` 解析） | 上下文正确 |
| Source 回读内容必须与采集时 sha256 一致 | `sddsync/context.py` 的 `build_context` | 数据库真实参与 |
| 补丁应用后源码必须与基线不同 | `sddsync/cli.py` 的 `cmd_apply` | 代码修改有效 |
| 补丁 sha256 必须与 PowerContext 状态一致 | `sddsync/cli.py` 的 `cmd_apply` | 状态能够复用 |
| 6 项验收逐条核对 | `verify.py` | 全部必做项 |

`verify.py` 的第 6 项会**重新执行**修改前与修改后的 pytest，不依赖 `test-report.json` 的历史结论。
