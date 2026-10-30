# 一页技术说明：SDD 上下文管理系统（MiniMax × OceanBase）

## 1. 模块结构

```
                 ┌──────────────────── PowerContext Server（seekdb 后端） ────────────────────┐
                 │  Source 证据（规格/代码/测试/任务） · Memory（状态/Work Contract/Outcome） │
                 │  全文索引 → POST /v1/context/prepare                                     │
                 └───────────────▲───────────────────────────────┬──────────────────────────┘
        ingest（写 Source）     │                               │ 回读 + 检索
                 ┌─────────────┴───────────┐   prepare_context ┌─┴──────────────┐
                 │  sddsync/ingest.py      │◀─────────────────│sddsync/context.py│
                 └─────────────────────────┘                  └─┬──────────────┘
                                                               │ 上下文（含来源 sha256）
                                       ┌───────────────────────┴───────────────┐
                                       │  sddsync/minimax_client.py            │
                                       │  MiniMax-M3.1-Flash → unified diff     │
                                       └───────────────────────┬───────────────┘
                                                               │ patch
                                        apply（从 Memory 恢复状态）→ work/app/
                                                               │
                                                    pytest：改前失败 / 改后通过
```

调用入口：`minimax/run.sh`（CLI）或直接 `python minimax/verify.py`（验收）。
输入：任务定义 `tasks/task-001.yaml` + 工程资料；输出：开发上下文、补丁、任务状态、测试报告。

## 2. 上下文选择方式

`sddsync/context.py` 按任务定义装配上下文，四段固定结构：

1. **任务目标** —— 来自 `tasks/task-001.yaml` 的 `objective`；
2. **规格条款** —— 按 `spec.clauses`（R1/R2）从规格文件精确抽取条款正文，
   每条附 `[source: minimax:<路径>:<内容 sha256 前 16 位>]`；
3. **代码符号** —— 用 `ast` 解析源码，给出 `compute_refund (sample-app/src/refund.py:L27-L33)`
   这样的真实行号与函数体；
4. **测试用例** —— 列出目标测试与全部回归测试的 id 与行号。

之后追加两段数据库来源：

* `## PowerContext 证据回读`：从 Source API 重新读回三个文件并复核 sha256；
* `## 数据库检索结果（seekdb 全文索引）`：`prepare_context` 的实际召回正文。

**选择依据**：任务定义里声明了必须包含什么（`required_context_tokens`、
`spec.clauses`、`code.symbols`、`tests.ids`），模块据此定位，
缺任何一项直接失败，绝不返回"看起来像"的答案。
**规格变化可感知**：Source id 含内容 sha256，规格一改 → Source id 变 → 上下文摘要变 →
旧补丁不再命中，必须重新生成（v2/v3 两套补丁即为实证）。

## 3. 三项技术的分工

| 技术 | 承担的角色 | 落点 |
| --- | --- | --- |
| **MiniMax**（`MiniMax-M3.1-Flash`） | 依据上下文实际生成代码修改补丁 | `sddsync/minimax_client.py` → `logs/minimax/calls.jsonl`、`patches/*.patch`、`docs/minimax-development-log.md` |
| **seekdb**（embedded，`pylibseekdb`） | 存储工程资料与索引，检索结果用于构造上下文 | Server 后端 `data/pc/seekdb`；取证见 `logs/db/inspect.md`、`logs/db/queries.sql` |
| **PowerContext** | 保存任务进展与验证结果，重启后读取并使用 | Work Contract / Memory 状态 / Task Outcome；`sddsync/state.py`、`sddsync/pc_client.py` |

## 4. 使用的 PowerContext API

| 用途 | API |
| --- | --- |
| Scope | `POST /v1/scopes`（幂等 key） |
| Source 证据 | `POST /v1/sources/content`、`GET /v1/scopes/{scope}/sources/content/{id}` |
| 召回上下文 | `POST /v1/context/prepare` |
| Work Contract | `POST /v1/work/contracts/create` |
| Task Outcome | `POST /v1/work/outcomes/record` |
| 任务状态 | `POST /v1/memory/remember`、`POST /v1/memory/entries/list` |

## 5. 关键边界

* **不改上游代码**：全部逻辑在 `minimax/` 内，PowerContext 只以 HTTP API 被调用。
* **基线只读**：`sample-app/` 永远是修改前状态，补丁只应用到 `work/app/` 副本，
  因此「改前失败 / 改后通过」可无限次复跑。
* **状态不落本地文件**：`apply` 只从 Memory 取状态、再回读 Work Contract；
  本地 `work/meta.json` 仅供查看，不参与恢复。
* **指纹口径统一**：补丁 sha256 一律按**文件原始字节**计算，
  Windows / Linux 两侧一致（补丁文件统一 LF 行尾）。
* **不伪造真实参与**：`verify.py` 区分 `real` / `assistant_session` / `mock`，
  有 key 却拿 mock 产物直接判 FAIL。
* **测试集前后一致**：补丁只触碰 `src/refund.py`，测试文件与预期值未被改动。

## 6. 验收自检

`python minimax/verify.py` 覆盖题面六项必做项：

| 项 | 检查内容 | 落点 |
| --- | --- | --- |
| 1 能运行 | 19 个交付产物齐全 + Server ready | `check_runnable` |
| 2 MiniMax 真实参与 | 调用记录 / 补丁 / 索引 / 开发记录四方 sha256 一致 | `check_minimax` |
| 3 上下文正确 | 条款、符号行号、用例 id、Source 可回查 | `check_context` |
| 4 数据库真实参与 | seekdb 表/行数、5 类关键证据命中、Source 回读复核 | `check_database` |
| 5 状态能够复用 | 重启（PID 变化）后从 Memory 恢复并复用 | `check_restart_reuse` |
| 6 代码修改有效 | 重跑 pytest：改前 AssertionError、改后全通过 | `check_modification` |
