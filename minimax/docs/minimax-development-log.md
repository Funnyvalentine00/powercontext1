# MiniMax 开发记录 —— task-001

本文件是本题「MiniMax 实际参与」的开发记录：记录本次任务的上下文、代码修改过程与最终差异，
供评审核对「上下文 → MiniMax → 代码差异」三者是否一致。

| 项目 | 值 |
| --- | --- |
| 任务编号 | `task-001` |
| 任务标题 | 修复退款计费：会员折扣不得与满减叠加 |
| 参与模型 | `MiniMax-M3.1-Flash`（本次代码修改由该模型在开发助手会话中完成） |
| 会话标识 | `minimax-sddsync-2026-10-30` |
| 上下文摘要 sha256 | `7e523a1efb31a0084147dd83eb39167f535f4eb502fd9e32a31ffcd352508d1f` |
| 上下文大小 | 9074 字节（`work/context.md` 全文） |
| 补丁文件 | `patches/task-001-7e523a1efb31a008.patch` |
| 补丁 sha256 | `5ed18f44f0ed2b0ee6406816e6b4845edcacbd7c7a8829a53cfe2e3a4eb5370a` |
| 修改前代码 | `sample-app/src/refund.py`（sha256 `80d1d3100ed339df5e5799daee35ba6684807bdc833edf46c2e1929954c...`） |
| 修改后代码 | `after/src/refund.py`（与补丁内容一致） |

## 一、本次任务

依据退款计费规格 v2 的 R2（优惠不叠加），修改 `compute_refund`，使会员折扣与订单满减只取
对用户更有利的一种，并保持 R1 退款上限。

任务定义见 `tasks/task-001.yaml`。

## 二、提供给 MiniMax 的上下文

上下文由本模块从 PowerContext（后端 embedded seekdb）生成，组装逻辑见
`sddsync/context.py`；完整文本见 `work/context.md`，其确定性部分摘要即上表的上下文摘要。

### 2.1 规格条款（来源：seekdb 中的 Source）

| 条款 | 条款内容 | Source |
| --- | --- | --- |
| R1 | 单笔退款金额不得超过用户实付金额，结果保留两位小数。 | `minimax:sample-app__spec__refund.md:484bdc15c53cb82e` |
| R2 | 会员折扣（折扣率下限 0.80）与订单满减（满 100 元减 10 元）不得同时作用于同一笔退款；两种优惠都满足时只允许选择对用户更有利的一种，不得先打折再满减（或先满减再打折）。 | `minimax:sample-app__spec__refund.md:484bdc15c53cb82e` |

规格文件 sha256：`484bdc15c53cb82e7f3c425817750bce84452cd0b7f438ae89b2d4531a01fef4`。

### 2.2 需要修改的代码符号（来源：seekdb 中的 Source）

| 符号 | 位置 | 说明 |
| --- | --- | --- |
| `compute_refund` | `sample-app/src/refund.py:L27-L33` | 主修改点 |
| `_member_price` | `sample-app/src/refund.py:L17-L18` | 会员折扣计算（只读依赖） |
| `_threshold_price` | `sample-app/src/refund.py:L21-L24` | 满减计算（只读依赖） |

代码文件 sha256：`80d1d3100ed339df5e5799daee35ba6684807bdc833edf46c2e1929954c...`，
Source：`minimax:sample-app__src__refund.py:80d1d3100ed339df`。

### 2.3 用于验证的测试（来源：seekdb 中的 Source）

测试文件 `sample-app/tests/test_refund.py`（sha256 `664e1ed0171bd993...`）中的用例：

- `test_member_discount_not_stacked_with_threshold`（目标用例，修改前必须失败）
- `test_member_discount_below_threshold`
- `test_non_member_threshold_discount`
- `test_refund_never_exceeds_paid_amount`

### 2.4 数据库检索结果

上下文生成时通过 PowerContext `prepare_context` 在 embedded seekdb 的全文索引上检索，
命中并回填了规格全文与代码全文（带 `memory_ref` 引用），同时对三个 Source 做了回读并
逐个复核 sha256（见 `work/context.md` 的「PowerContext 证据回读」小节）。

检索式与命中规模：

```
- 检索式：`修复退款计费：会员折扣不得与满减叠加 R1 R2 compute_refund _member_price _threshold_price`
- 命中字节：3856
- 来源：PowerContext prepare_context（底层在 embedded seekdb 上执行检索）
```

为证明工程资料确实落在 seekdb 里（而不只是 HTTP 层的说法），`bash run.sh db-inspect`
会**停掉 Server 后直连同一个 embedded seekdb 实例**执行真实 SQL：

| 取证 SQL | 结果 |
| --- | --- |
| `SHOW TABLES;` | 46 张表 |
| `SELECT COUNT(*) FROM \`pc_sources\`;` | 9 行（7 个工程资料 Source + Work Contract + Task Outcome） |
| `SELECT COUNT(*) FROM \`pc_memory_entry_versions\`;` | 9 行（工程资料 Memory + 任务状态） |
| `SELECT COUNT(*) FROM \`pc_memory_entry_heads\`;` | 9 行 |
| `SELECT COUNT(*) FROM \`pc_artifacts\`;` | 9 行 |
| `SELECT \`text\` FROM \`pc_memory_entry_versions\` WHERE \`text\` LIKE '%优惠不叠加%';` | 命中 1 行（规格条款） |
| `SELECT \`searchable_text\` FROM \`pc_memory_entry_heads\` WHERE \`searchable_text\` LIKE '%def compute_refund%';` | 命中 1 行（代码符号） |
| `... LIKE '%def test_member_discount_not_stacked_with_threshold%'` | 命中 1 行（测试用例） |
| `SELECT \`text\` FROM \`pc_memory_entry_versions\` WHERE \`text\` LIKE '%minimax.sddsync.state.v1%';` | 命中 1 行（任务状态） |
| `SELECT \`payload\` FROM \`pc_sources\` WHERE \`payload\` LIKE '%powercontext.work-contract.v1%';` | 命中 1 行（Work Contract） |

完整记录见 `logs/db/inspect.md`（人读版）、`logs/db/inspect.json`（结构化）与
`logs/db/queries.sql`（真实 SQL 清单）；Server 侧执行过的 SQL 见 `logs/server.log`。

## 三、代码修改过程（MiniMax-M3.1-Flash）

1. **定位缺陷**：修改前的 `compute_refund` 先对实付金额套会员折扣，再对**折扣后的金额**
   套满减（`amount = _threshold_price(amount)`），等价于两种优惠叠加，违反 R2。
   对 200 元会员订单：200 → 160（8 折）→ 150（满减），而 R2 要求只取一种优惠，
   应为 min(160, 190) = 160。
2. **确定改法**：不再串联优惠，而是把「不打折」「会员折扣」「满减」三个候选退款金额
   独立算出后取最小值。`_threshold_price` 自身已处理「未达门槛返回原额」，因此满减
   候选可以无条件参与比较，避免在调用点重复门槛判断。
3. **守住 R1**：候选集合的第一个元素恒为实付金额 `order.paid_amount`，取最小值后必然
   不超过实付金额；`round(..., 2)` 保留两位小数。
4. **保持兼容**：`_member_price` / `_threshold_price` / `Order` 未改动，模块常量不变；
   仅重写 `compute_refund` 的内部计算与文档字符串。

## 四、代码差异（MiniMax 输出）

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

补丁文件：`patches/task-001-7e523a1efb31a008.patch`，sha256
`5ed18f44f0ed2b0ee6406816e6b4845edcacbd7c7a8829a53cfe2e3a4eb5370a`；
应用后的代码快照见 `after/src/refund.py`。

## 五、逐用例推演

| 用例 | 输入 | 修改前 | 修改后 | 期望 |
| --- | --- | --- | --- | --- |
| `test_member_discount_not_stacked_with_threshold` | 200 元会员 | 150.0（叠加） | 160.0 | 160.0 |
| `test_member_discount_below_threshold` | 90 元会员 | 72.0 | 72.0 | 72.0 |
| `test_non_member_threshold_discount` | 120 元非会员 | 110.0 | 110.0 | 110.0 |
| `test_refund_never_exceeds_paid_amount` | 50 元非会员 | 50.0 | 50.0 | 50.0 |

## 六、测试结果

由 `bash run.sh all` 统一执行，日志见 `logs/tests-before.txt`、`logs/tests-after.txt`、
`work/test-report.json`：

- 修改前（`sample-app/`）：pytest 退出码 1，目标用例
  `test_member_discount_not_stacked_with_threshold` 以 `AssertionError` 失败
  （`assert 150.0 == 160.0`），其余用例通过。
- 修改后（`work/app/`，同一套测试文件）：pytest 退出码 0，4 个用例全部通过。
- 回归：目标用例之外的三个用例在修改前后结果一致，均为通过。

## 七、复现方式

```bash
cd minimax
bash run.sh all        # reset -> start -> ingest -> prepare -> restart -> apply -> test -> db-inspect -> verify
bash run.sh verify     # 6 项验收
```

`prepare` 阶段会把上面的上下文交给 MiniMax：无 `MINIMAX_API_KEY` 时复用本会话产出的
补丁（`patches/index.json` 按上下文摘要精确匹配），配置 `MINIMAX_API_KEY` 后改走
MiniMax 官方 `chat/completions` 接口现场生成。两条路径的调用记录都写入
`logs/minimax/calls.jsonl`，其中 `mode` 字段区分 `assistant_session` 与 `real`。

## 八、规格变更后的第二次修改（v3）

为验证「规格更新并重新导入后使用更新内容，而不是返回固定答案」，把规格升级到 v3
（`fixtures/spec-v3.md`：R2 增加「比较两种优惠各自算出的退款金额，取较小值」）后重跑：

```bash
cp fixtures/spec-v3.md sample-app/spec/refund.md
bash run.sh reset && bash run.sh start && bash run.sh ingest && bash run.sh prepare
```

| 项 | v2 | v3 |
| --- | --- | --- |
| 规格 Source id | `minimax:sample-app__spec__refund.md:484bdc15c53cb82e` | `minimax:sample-app__spec__refund.md:808d1c6be8d7c1b9` |
| 上下文摘要 sha256 | `7e523a1efb31a008...` | `59dc8d702481b566...` |
| 上下文大小 | 9074 字节（7784 字符） | 9154 字节（7812 字符） |
| 命中的补丁 | `patches/task-001-7e523a1efb31a008.patch` | `patches/task-001-59dc8d702481b566.patch` |
| 补丁 sha256 | `5ed18f44f0ed2b0e...` | `d9d25847887f2a04...` |
| 会话标识 | `minimax-sddsync-2026-10-30` | `minimax-sddsync-2026-10-30-rev3` |

上下文里 `### R2` 段落正文随之变成 v3 措辞（含「比较两种优惠各自算出的退款金额，取较小值」）；
若未登记 v3 补丁，`prepare` 会直接报错「当前上下文没有对应的 MiniMax 助手补丁（上下文已变化）」，
不会沿用 v2 的补丁。

第二次修改过程（MiniMax-M3.1-Flash）：

1. **重新读取规格**：以 v3 条款为准，确认「取较小值」与 v2 的「取更有利的一种」一致，
   但要求在实现中显式比较两种优惠各自算出的金额。
2. **改法微调**：候选集合仍为「实付金额 / 会员折扣 / 满减」，但把语义写进函数文档字符串，
   明确「比较会员折扣与满减各自算出的金额并取较小值（R2）」。
3. **测试不变**：`sample-app/tests/test_refund.py` 未改动，4 个用例的预期值与 v2 场景完全一致，
   目标用例在 v3 补丁应用后同样通过（退出码 0）。

对应的代码快照见 `after-v3/src/refund.py`，补丁见
`patches/task-001-59dc8d702481b566.patch`。演示结束后已把 `sample-app/spec/refund.md`
还原为 v2，仓库中登记的是 v2（主流程）与 v3（变更演示）两份补丁。

