# MiniMax SDD 上下文管理（生态题）

用 PowerContext 把「规格条款 → 代码符号/行号 → 测试用例」组织成可复用的任务上下文，
交给 MiniMax 生成补丁；Work Contract、任务状态与 Task Outcome 全部写入 PowerContext，
重启后从数据库恢复，最后用修改前后的 pytest 对比证明修改有效。

验证样例见 [`docs/verification-sample.md`](docs/verification-sample.md)（评审从这里开始）。

---

## 1. 目录结构

```
minimax/
  run.sh                        # start/stop/restart/status/reset/ingest/prepare/apply/test/db-inspect/all/verify
  verify.py                     # 6 项验收自动检查（退出码 0 = 全过）
  .env.example                 # 配置示例（占位值，无真实凭据）
  requirements.txt              # 依赖说明
  sddsync/                      # 上下文模块
    cli.py                      # 命令入口
    pc_client.py                # PowerContext HTTP API 薄客户端（仅标准库）
    ingest.py                   # 规格/代码/测试 → Source（落 seekdb）+ Memory 条目
    context.py                  # 按任务拼装上下文（条款/符号行号/用例 id）
    minimax_client.py           # MiniMax 接入层：官方 API / 编码助手会话 / Mock
    state.py                    # Work Contract、任务状态、Task Outcome
    seekdb_probe.py             # 直连 embedded seekdb 执行真实 SQL 取证
  sample-app/                   # 只读基线工程（改前必失败的 4 个测试）
  after/                        # 修改后代码快照（v2 规格）
  after-v3/                     # 修改后代码快照（v3 规格，规格变更演示用）
  fixtures/                     # spec-v1 / spec-v2 / spec-v3 规格文本
  tasks/task-001.yaml           # 任务定义 + 必须包含的条款/符号/测试 id
  patches/                      # MiniMax 产出的补丁 + index.json（上下文 sha256 -> 补丁登记）
  docs/                         # 验证样例、开发记录、代码差异
```

---

## 2. 依赖版本

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.11+ | PowerContext 要求 `>=3.11,<4.0` |
| PowerContext | 参赛仓库 `2026-competition` 分支的 `src/` | 以 `PYTHONPATH` 方式引用，不改动上游代码 |
| embedded seekdb | `pylibseekdb>=1.4.0.post1,<2` | OceanBase 兼容嵌入式引擎，MySQL 协议（本地实测 `1.4.0.post2`） |
| aiomysql | `>=0.2`（实测 `0.3.2`） | 直连 seekdb 执行取证 SQL |
| pymysql | `>=1.1,<1.2.1`（实测 `1.2.0`） | **必须锁 `<1.2.1`**：1.2.1+ 把 `converters.escape_bytes_prefixed` 换成哨兵字符串，aiomysql 0.3.2 仍在调用它，写入 Source 会报 `TypeError: 'str' object is not callable` |
| pyobvector / SQLAlchemy | `>=0.2.28` / `>=2`（实测 `0.2.29` / `2.0.54`） | PowerContext 检索层依赖 |
| pytest / pyyaml | `>=8` / `>=6`（实测 `9.0.2` / `6.0.3`） | 样例测试与任务定义解析 |
| MiniMax 模型 | `MiniMax-M3.1-Flash` | 见 `logs/minimax/calls.jsonl` |

### 安装（一键自举）

参赛分支 `2026-competition-ecosystem` 只带 `minimax/` 资产、不含 `src/`，
所以先执行自举脚本，它会准备好源码与虚拟环境：

```bash
cd minimax
bash bootstrap.sh          # 幂等；首次需要联网下载依赖
```

`bootstrap.sh` 的动作：

1. **准备 PowerContext 源码**，按以下顺序取第一个可用来源：
   1. 环境变量 `POWERCONTEXT_SRC` 指向的 `src/` 目录；
   2. 仓库同级的 `../src/`（若你把整个 PowerContext 仓库放在旁边）；
   3. 参赛仓库自身的 `2026-competition` 分支（用 `git archive` 取出 `src/` 与 `pyproject.toml`，**不需要联网**）；
   4. 从上游 `github.com/oceanbase/powercontext` 浅克隆 `2026-competition` 分支。
2. **建虚拟环境** `$ROOT/.venv`（有 `uv` 就用 `uv venv --python 3.12`，否则 `python3 -m venv`），并校验 Python ≥ 3.11。
3. **安装依赖**：`pip install -e <源码目录>[server]`（含 fastapi/uvicorn/sqlalchemy/pyobvector 等）、
   `pylibseekdb>=1.4.0.post1,<2`、`aiomysql`、`pymysql>=1.1,<1.2.1`、`pytest`、`pyyaml`。
   源码不是 git 仓库时自动用 `SETUPTOOLS_SCM_PRETEND_VERSION` 绕过版本探测；
   pymysql 版本会被无条件校正到 `<1.2.1`（原因见上表）。
4. **自检**：打印各包版本并导入 `powercontext.server.factory` 验证可用。

装好后：

```bash
PYTHON=$PWD/.venv/bin/python bash run.sh all
```

> `pylibseekdb` 只提供 Linux / macOS wheel；Windows 上会回退到 `sqlite` 后端并在日志中提示。
> 但**本题的「数据库实际参与」验收项需要 seekdb 后端**，请在 Linux 环境下运行。


---

## 3. 配置

```bash
cd minimax
cp .env.example .env      # 可选，不配置也能跑
```

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MINIMAX_API_KEY` | 空 | 填入则走官方 `chat/completions` 实时调用（`mode=real`） |
| `MINIMAX_BASE_URL` | `https://api.minimax.cn/v1` | MiniMax OpenAI 兼容接口地址 |
| `MINIMAX_MODEL` | `MiniMax-M3.1-Flash` | 使用的模型 |
| `DATABASE_KIND` | `seekdb` | `seekdb`（本题默认）或 `sqlite` |
| `POWERCONTEXT_URL` | `http://127.0.0.1:8311` | Server 地址 |
| `POWERCONTEXT_PORT` | `8311` | Server 端口 |

---

## 4. 快速开始

```bash
cd minimax
bash run.sh all        # reset → start → ingest → prepare → restart → apply → test → db-inspect → verify
```

预期末行：`结果: 6 PASS / 0 SKIP / 0 FAIL`（退出码 0）。

单步执行：

```bash
bash run.sh reset       # 清空 data/ work/ logs/，回到修改前基线
bash run.sh start       # 启动 PowerContext Server（seekdb 后端）
bash run.sh ingest      # 导入规格/代码/测试到 PowerContext Source（落 seekdb）
bash run.sh prepare     # 装配上下文 + Work Contract，调用 MiniMax 产出补丁
bash run.sh restart     # 重启 Server（验证状态复用）
bash run.sh apply       # 从 PowerContext 恢复状态，把补丁应用到 work/app
bash run.sh test        # 修改前 / 修改后各跑一轮 pytest
bash run.sh db-inspect  # 直连 seekdb 执行真实 SQL，导出数据库取证材料
bash run.sh status      # 查看 Scope / Source / Memory / 任务状态
bash run.sh verify      # 6 项验收
bash run.sh stop        # 停 Server
```

`run.sh` 会自动选择解释器：优先 `PYTHON` 环境变量，其次 `minimax/.venv/bin/python`
（即 `bootstrap.sh` 建好的虚拟环境），最后回退到系统 `python3`；
也可用 `PYTHON=<python> bash run.sh all` 显式指定。

---

## 5. MiniMax 接入方式

| 模式 | 触发条件 | 说明 | 验收第 2 项 |
| --- | --- | --- | --- |
| `real` | 设置了 `MINIMAX_API_KEY` | 官方 `POST {base_url}/chat/completions`，记录完整请求/响应 | PASS |
| `assistant_session` | 无 key，但 `patches/index.json` 存在 | 复用本次 MiniMax 编码助手会话产出的补丁，按**上下文 sha256 精确匹配** | PASS |
| `mock` | 无 key 且无补丁索引 | `difflib` 生成确定性 diff | SKIP（不计分） |

`assistant_session` 的意义：规格一改，上下文摘要就变，旧补丁不再命中，
必须重新由 MiniMax 生成 —— 与「规格更新后必须使用更新内容」的要求一致。
补丁登记见 `patches/index.json`：

```json
{
  "task_id": "task-001",
  "file": "task-001-7e523a1efb31a008.patch",
  "context_sha256": "7e523a1e...",
  "patch_sha256": "5ed18f44...",
  "model": "MiniMax-M3.1-Flash",
  "session": "minimax-sddsync-2026-10-30",
  "spec_version": "v2"
}
```

每次调用都写入 `logs/minimax/calls.jsonl`（mode/purpose/model/base_url/session/
context_sha256/patch_file/patch_sha256/messages/response_text/latency_ms）。

---

## 6. 数据库

默认 `DATABASE_KIND=seekdb`：PowerContext Server 以 embedded seekdb 为后端，
工程资料（规格/代码/测试/任务定义）写入 `pc_sources`，同时以 Memory 条目形式入库，
`POST /v1/context/prepare` 在 seekdb 全文索引上检索，检索结果回填进开发上下文。

数据目录：`data/pc/seekdb/`（进程工作目录下的运行态，不入库）。

`bash run.sh db-inspect` 会直连该实例执行真实 SQL（`SHOW TABLES`、逐表 `SELECT COUNT(*)`、
`SHOW COLUMNS`、`LIKE` 取证检索），输出到 `logs/db/inspect.{json,md}` 与 `logs/db/queries.sql`。

回退：`DATABASE_KIND=sqlite` 使用 `data/pc/powercontext.db`，可移植但不是本题要求的数据库。

---

## 7. 产物位置

| 产物 | 路径 |
| --- | --- |
| 上下文 | `work/context.md` |
| 补丁（运行产物） | `work/patch.diff` |
| 任务状态元数据 | `work/meta.json` |
| 测试结果 | `work/test-report.json` |
| 打补丁后的工作副本 | `work/app/` |
| MiniMax 调用日志 | `logs/minimax/calls.jsonl` |
| 测试日志 | `logs/tests-before.txt`、`logs/tests-after.txt` |
| 数据库取证 | `logs/db/inspect.{json,md}`、`logs/db/queries.sql` |
| Server 日志 | `logs/server.log` |

---

## 8. 已知限制

* `assistant_session` 模式要求仓库里存在与当前上下文摘要匹配的补丁；
  规格改动后若未登记新补丁，`prepare` 会明确报错，不会静默使用旧补丁。
* 真实 MiniMax 输出若不是合法 unified diff，`extract_unified_diff` 会直接失败
  （不会伪造补丁）。
* `pylibseekdb` 仅提供 Linux / macOS wheel；Windows 上会回退到 sqlite。
* 未启用向量检索，`prepare_context` 的召回依赖显式写入的 Memory 条目；
  规格/代码证据另有 Source 回读 + sha256 复核兜底。
* 上下文摘要只覆盖确定性头部（任务/规格/代码/测试），不覆盖回读与检索片段，
  以保证同一份输入工程摘要稳定、可精确复用补丁。
