# 验证样例：修复退款计费（会员折扣不得与满减叠加）

本文件是本作品的验证样例，供评审从干净环境逐条复现。
每一步都给出命令、退出码与预期结果；命令均为仓库根目录 `minimax/` 下的相对路径。

---

## 1. 任务描述

| 项 | 内容 |
| --- | --- |
| 任务 id | `task-001` |
| 标题 | 修复退款计费：会员折扣不得与满减叠加 |
| 要改什么 | `sample-app/src/refund.py` 中的 `compute_refund`：当前实现先打会员 8 折再减满减，把两种优惠叠加了；需要改成会员折扣与订单满减**只取对用户更有利的一种** |
| 哪些原有行为必须保持 | R1 退款上限（不超过实付金额，保留两位小数）；非会员满减行为不变；低于门槛的会员订单仍按 8 折计算 |
| 规格版本 | v2（`sample-app/spec/refund.md`） |
| 目标测试 | `test_member_discount_not_stacked_with_threshold`（修改前必须因行为未实现而失败） |
| 回归测试 | `test_member_discount_below_threshold`、`test_non_member_threshold_discount`、`test_refund_never_exceeds_paid_amount` |

任务定义文件：[`tasks/task-001.yaml`](../tasks/task-001.yaml)。

---

## 2. 有效规格：上下文中必须包含的来源

模块产出的上下文（`work/context.md`）必须能定位下列来源，且每段内容都带真实存在的
`[source: ...]` 引用（`minimax:<扁平化路径>:<内容 sha256 前 16 位>`）。
缺任何一项，`prepare` 会直接失败，不会产出半成品上下文。

| 类别 | 必须包含 | 来源路径 | Source id（本次运行实测） |
| --- | --- | --- | --- |
| 规格条款 | `R1` 退款上限 | `sample-app/spec/refund.md` | `minimax:sample-app__spec__refund.md:484bdc15c53cb82e` |
| 规格条款 | `R2` 优惠不叠加 | `sample-app/spec/refund.md` | 同上 |
| 代码符号 | `compute_refund`（带行号 `sample-app/src/refund.py:L27-L33`） | `sample-app/src/refund.py` | `minimax:sample-app__src__refund.py:80d1d3100ed339df` |
| 代码符号 | `_member_price`（L17-L18）、`_threshold_price`（L21-L24） | `sample-app/src/refund.py` | 同上 |
| 测试用例 | `test_member_discount_not_stacked_with_threshold`（L10-L12） | `sample-app/tests/test_refund.py` | `minimax:sample-app__tests__test_refund.py:664e1ed0171bd993` |
| 测试用例 | 另外 3 个回归用例（各自带行号） | `sample-app/tests/test_refund.py` | 同上 |
| 代码全文 | 生成补丁所需的 `src/refund.py` 全文 | `sample-app/src/refund.py` | 同上 |
| 任务状态 | Work Contract（目标、上下文摘要、证据清单） | PowerContext Source | `minimax:work-contract:task-001:v1` |

上下文里的硬性校验 token 来自 `tasks/task-001.yaml` 的 `required_context_tokens`：
`R2`、`compute_refund`、`test_member_discount_not_stacked_with_threshold`。

此外，上下文末尾固定包含两段由数据库产出的内容：

* `## PowerContext 证据回读` —— 生成上下文时用 `GET /v1/sources/content/{id}` 从数据库
  重新读回规格/代码/测试三个 Source 并复核 sha256，证明上下文不是凭空拼的；
* `## 数据库检索结果（seekdb 全文索引）` —— `POST /v1/context/prepare` 在 embedded seekdb
  的全文索引上检索到的工程资料片段（本次命中 3856 字节，含任务定义、源码、历史规格 v1）。

> 上下文中「证据回读」之后的内容随数据库运行状态变化，因此**上下文摘要只覆盖确定性头部**
> （任务/规格/代码/测试）。规格一改，Source id 与摘要随之改变，必须重新生成补丁。

---

## 3. 初始数据

初始状态由 `bash run.sh reset` 建立，不需要任何手工准备：

| 数据 | 位置 | 说明 |
| --- | --- | --- |
| 规格（当前） | `sample-app/spec/refund.md` | v2，R1/R2 两条 |
| 规格（历史） | `fixtures/spec-v1.md` | v1，R2 允许叠加，用于演示"历史规格不能被误用" |
| 规格（修订） | `fixtures/spec-v3.md` | v3，仅用于第 8 节的规格变更演示 |
| 代码基线 | `sample-app/src/refund.py` | **故意违反 R2** 的实现，补丁只应用到 `work/app/` 副本 |
| 测试 | `sample-app/tests/test_refund.py` | 4 个用例，其中 1 个在基线上必失败 |
| 任务定义 | `tasks/task-001.yaml` | 任务目标、条款、符号、用例 id、必需 token |
| 数据库 | `data/pc/seekdb/` | embedded seekdb（pylibseekdb），由 `ingest` 写入工程资料 |
| PowerContext 状态 | `data/pc/seekdb` 内的 `pc_sources` / `pc_memory_entry_versions` / `pc_artifacts` | Source、Memory、Work Contract、Task Outcome |

`reset` 之后 `sample-app/` 保持基线（不满足规格），`work/` 与 `logs/` 为空，
数据库目录为空 —— 评审可确认"从空状态开始"。

---

## 4. 操作步骤（主流程）

### 4.0 从干净环境开始（首次）

参赛分支 `2026-competition-ecosystem` 只带 `minimax/` 资产、不含 PowerContext 的 `src/`
与虚拟环境，先执行自举脚本：

```bash
cd minimax
bash bootstrap.sh
```

它会准备 PowerContext 源码（优先从本仓库 `2026-competition` 分支用 `git archive` 取出，
**不依赖外网**）、建好 `.venv`、安装依赖并自检。成功后进入 4.1。

### 4.1 主流程

```bash
cd minimax
bash run.sh all
```

`all` 依次执行 `reset → start → ingest → prepare → restart → apply → test → db-inspect → verify`，
每一步的实际输出如下（本次实测）：

| 步骤 | 命令 | 预期输出（关键行） | 退出码 |
| --- | --- | --- | --- |
| 初始化 | `bash run.sh reset` | `[reset] 已清理 data/ work/ logs/，样例工程恢复为未修复基线` | 0 |
| 启动 | `bash run.sh start` | Server ready，监听 `127.0.0.1:8311`，后端 `seekdb` | 0 |
| 导入资料 | `bash run.sh ingest` | `[ingest] 7 个 Source 已写入 PowerContext scope=scp_...` | 0 |
| 生成上下文 | `bash run.sh prepare` | `[prepare] 上下文 7784 字符 sha256=7e523a1efb31a008`<br>`[prepare] Work Contract -> minimax:work-contract:task-001:v1`<br>`[prepare] MiniMax mode=assistant_session model=MiniMax-M3.1-Flash patch sha256=5ed18f44f0ed2b0e` | 0 |
| 重启 | `bash run.sh restart` | Server PID 变化 | 0 |
| 恢复状态并打补丁 | `bash run.sh apply` | `[apply] 已从 PowerContext 恢复状态（contract=minimax:work-contract:task-001:v1）`<br>`[apply] 补丁已应用到 .../minimax/work/app` | 0 |
| 跑测试 | `bash run.sh test` | `[test] 修改前 exit=1（目标用例以 AssertionError 失败=True）`<br>`[test] 修改后 exit=0（全部通过=True）` | 0 |
| 数据库取证 | `bash run.sh db-inspect` | `[db-inspect] seekdb 46 张表，共 52 行 -> .../logs/db/inspect.md` | 0 |
| 验收 | `bash run.sh verify` | 6 项全部 `[PASS]`，末行 `结果: 6 PASS / 0 SKIP / 0 FAIL` | 0 |

单独执行某一步：`bash run.sh reset|start|ingest|prepare|restart|apply|test|db-inspect|status|stop`。

---

## 5. 预期结果

### 5.1 上下文输出

`work/context.md` 必须同时出现：

* `### R1` / `### R2` 两条规格条款，且每条带 `[source: minimax:sample-app__spec__refund.md:...]`；
* `### compute_refund (sample-app/src/refund.py:L27-L33)` 与两个私有函数；
* 4 个 `### sample-app/tests/test_refund.py::test_xxx (Lxx-Lxx)` 条目；
* `## PowerContext 证据回读` 段的 3 条 `[readback: ... sha256=...]`；
* `## 数据库检索结果（seekdb 全文索引）` 段的检索式、命中字节数与召回正文。

`verify.py` 的第 3 项会逐条核对上述内容，缺一即 FAIL。

### 5.2 代码修改有效

修改前（`sample-app/`，即基线）：

```
F...                                                                     [100%]
>       assert compute_refund(order) == 160.00
E       assert 150.0 == 160.0
tests/test_refund.py:12: AssertionError
1 failed, 3 passed in 0.02s
```

退出码 `1`，失败原因是 `AssertionError`（行为未实现），**不是** 缺依赖/无法启动。

修改后（`work/app/`）：

```
....                                                                     [100%]
4 passed in 0.01s
```

退出码 `0`，4 个用例全通过（含 3 个回归用例）。结果同时写入
`work/test-report.json`（`before.exit_code=1`、`before.target_failed_with_assertion=true`、
`after.exit_code=0`、`after.all_passed=true`）与 `logs/tests-before.txt`、`logs/tests-after.txt`。

### 5.3 数据库真实参与

`logs/db/inspect.md` 与 `logs/db/inspect.json` 记录了直连 embedded seekdb 执行的真实 SQL：
`SHOW TABLES`（46 张表）、逐表 `SELECT COUNT(*)`（合计 52 行）、`SHOW COLUMNS`，
以及对工程资料的 `LIKE` 取证检索，命中 5 类关键证据：

| 标签 | 命中内容 |
| --- | --- |
| 规格条款 | `优惠不叠加` |
| 代码符号 | `def compute_refund` |
| 测试用例 | `def test_member_discount_not_stacked_with_threshold` |
| 任务状态 | `minimax.sddsync.state.v1` |
| Work Contract | `powercontext.work-contract.v1` |

`logs/db/queries.sql` 导出上述可复跑的 SQL 语句。

### 5.4 状态复用

`apply` 阶段从 PowerContext Memory 读回任务状态（`state_loaded_from=powercontext-memory`），
再按 `contract_source_id` 回读 Work Contract 并比对目标与补丁 sha256；
`verify.py` 第 5 项会再次重启 Server（PID 变化），确认重启后仍能恢复并复用状态。

### 5.5 MiniMax 真实参与

`logs/minimax/calls.jsonl` 每条记录包含 `mode`、`purpose`、`model`、`base_url`、
`session`、`context_sha256`、`patch_file`、`patch_sha256`、完整 `messages` 与 `response_text`。

本次记录（`mode=assistant_session`）：

| 字段 | 值 |
| --- | --- |
| model | `MiniMax-M3.1-Flash` |
| session | `minimax-sddsync-2026-10-30` |
| context_sha256 | `7e523a1efb31a0084147dd83eb39167f535f4eb502fd9e32a31ffcd352508d1f` |
| patch_file | `task-001-7e523a1efb31a008.patch` |
| patch_sha256 | `5ed18f44f0ed2b0ee6406816e6b4845edcacbd7c7a8829a53cfe2e3a4eb5370a` |

对应的开发过程记录见 [`minimax-development-log.md`](minimax-development-log.md)，
代码差异见 [`code-diff.md`](code-diff.md)。

---

## 6. 重置方法

```bash
cd minimax
bash run.sh stop
bash run.sh reset     # 清空 data/ work/ logs/，样例工程回到修改前基线
```

`reset` 做的事：停掉 Server、删除 `data/`（含 seekdb 数据目录）、`work/`、`logs/`，
并把 `sample-app/src/refund.py` 还原为未修复基线（该文件是基线快照，`reset` 不会修改它，
补丁只写 `work/app/`）。

复现完成后想回到"从未运行过"的状态，删掉这三个目录即可：

```bash
rm -rf minimax/data minimax/work minimax/logs
```

---

## 7. 已知限制与不影响验收的前提

* `sample-app/` 是**只读基线**，`work/app/` 才是打补丁后的工作副本；
  评审可任意重跑 `test`，结果始终是"改前失败、改后通过"。
* 测试集在修改前后完全一致（`sample-app/tests/test_refund.py` 未被修改，
  补丁也只触碰 `src/refund.py`），没有删除断言、跳过测试或修改预期值。
* 无 `MINIMAX_API_KEY` 时走 `assistant_session` 模式：复用本次 MiniMax 编码助手会话产出的
  补丁，按上下文 sha256 精确匹配；配置了 key 则切换为官方 `chat/completions` 实时调用
  （`mode=real`）。`verify.py` 会区分两者并阻止把 mock 记成真实参与。

---

## 8. 规格变更演示（验收项「规格更新并重新导入后，输出使用更新内容」）

规格从 v2 升级到 v3（R2 增加「比较两种优惠各自算出的退款金额，取较小值」）后，
上下文必须使用更新后的条款，而不是返回固定答案。复现步骤：

```bash
cd minimax
cp fixtures/spec-v3.md sample-app/spec/refund.md   # 模拟规格升级
bash run.sh reset
bash run.sh start
bash run.sh ingest        # 重新导入：新的 Source id（旧 v2 Source 仍在库中，可查）
bash run.sh prepare       # 重新装配上下文
```

预期：

1. `sample-app/spec/refund.md` 的 Source id 变化：
   v2 `minimax:sample-app__spec__refund.md:484bdc15c53cb82e` →
   v3 `minimax:sample-app__spec__refund.md:<新 sha 前 16 位>`；
2. `work/context.md` 的 `### R2` 段落正文包含 v3 新增的括注
   「（比较两种优惠各自算出的退款金额，取较小值）」，而 v2 段落没有；
3. 上下文摘要随之改变为 `59dc8d702481b566...`，因此**旧的 v2 补丁不再命中**：
   若未登记 v3 补丁，`prepare` 会直接报错
   「当前上下文没有对应的 MiniMax 助手补丁（上下文已变化）」；
   登记 v3 补丁后（`patches/index.json` 中 `spec_version=v3` 的条目），
   生成的补丁 sha256 为 `d9d25847887f2a046b0774df654d224163a7b92ca8c40664de193ac3efd370bc`，
   与 v2 补丁不同 —— 证明模块按"当前规格"工作，而不是回放固定答案；
4. 恢复 v2：`git checkout sample-app/spec/refund.md && bash run.sh reset`。

`patches/index.json` 中 v2 / v3 两条登记即上述两次运行的产物，
`docs/minimax-development-log.md` 记录了两次修改过程。

---

## 9. 相关材料索引

| 材料 | 路径 |
| --- | --- |
| 源码（上下文模块） | `minimax/sddsync/` |
| 运行说明 | `minimax/README.md` |
| 一页技术说明 | `minimax/TECHNICAL-NOTE.md` |
| MiniMax 开发记录 | `minimax/docs/minimax-development-log.md` |
| 代码差异（改前/改后） | `minimax/docs/code-diff.md` |
| 数据库查询记录 | `minimax/logs/db/inspect.md`、`minimax/logs/db/queries.sql` |
| PowerContext 状态记录 | `minimax/logs/server.log`、`minimax/work/meta.json` |
| 测试日志 | `minimax/logs/tests-before.txt`、`minimax/logs/tests-after.txt` |
| MiniMax 调用日志 | `minimax/logs/minimax/calls.jsonl` |
| 验收脚本 | `minimax/verify.py` |
