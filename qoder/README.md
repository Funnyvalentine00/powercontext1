# 科研上下文助手（Qoder × OceanBase 生态题）

读了几十篇论文，结论记不住、引用找不到源头、隔几天接不上——这个工具解决这三件事。

它把文献切块存进 **seekdb**，按研究问题检索证据，产出一份**每条结论都能回到原文**的报告，
并在证据不足的地方明确写出「证据缺口」。研究任务的状态存进 **PowerContext**，
重启后能读回并接着上次继续。

核心取舍：**不调用大模型生成结论**。报告里的结论全部是被检索到的原文片段，
只做去重与排序，所以每一条都能按 `[En]` 编号回到数据库核对。这让「可核验」成为产品特性。

> 本目录是 Qoder 生态赛题的参赛作品。开发过程见 [`docs/qoder-dev-log.md`](docs/qoder-dev-log.md)，
> 设计与接口契约见 [`docs/DESIGN.md`](docs/DESIGN.md)，评审复现步骤见
> [`docs/verification-sample.md`](docs/verification-sample.md)。

---

## 1 目录结构

```
qoder/
  AGENTS.md                    # 给 AI agent 的运行约定（命令走 WSL）
  bootstrap.sh                 # 自举：准备 PowerContext 源码 + venv + 依赖
  run.sh                       # 统一入口（start/ingest/ask/resume/verify/all/test）
  requirements.txt             # 依赖说明
  src/rca/                     # 上下文模块
    cli.py                     # 命令入口（环境准备已可用，业务命令待实现）
    parser.py                  # 语料扫描与分块
    store.py                   # seekdb 连接、入库、检索
    textutil.py                # 中英混合分词与匹配打分
    evidence.py                # 子问题拆分、证据选择、缺口判定
    report.py                  # 报告渲染与解析
    state.py                   # PowerContext 任务状态与报告存取
    pc_client.py               # PowerContext HTTP 客户端（已完整可用）
  data/corpus/                 # 示例语料（6 篇，自造，替换成自己的论文即可）
  docs/                        # 设计说明、验证样例、Qoder 开发记录、站点文案
  tests/                       # 单元测试
```

---

## 2 依赖版本

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.11+（推荐 3.12） | PowerContext 要求 `>=3.11,<4.0` |
| PowerContext | 参赛仓库 `2026-competition` 分支的 `src/` | 以 `PYTHONPATH` 引用，不改动上游代码 |
| embedded seekdb | `pylibseekdb>=1.4.0.post1,<2` | OceanBase 兼容嵌入式引擎，MySQL 协议 |
| aiomysql | `>=0.2` | 直连 seekdb 执行取证 SQL |
| pymysql | `>=1.1,<1.2.1` | **必须锁 `<1.2.1`**：1.2.1+ 与 aiomysql 0.3.2 不兼容，写 Source 会报 `TypeError` |
| pytest / pyyaml | `>=8` / `>=6` | 单元测试 |

> `pylibseekdb` 只提供 Linux / macOS wheel。Windows 上请用 WSL 或 Docker 运行，
> 详见 `AGENTS.md`。本题的「数据库实际参与」需要真实的 seekdb，不能回退 sqlite。

---

## 3 安装（一键自举）

参赛分支 `2026-competition-ecosystem` 只带 `qoder/` 资产、不含 PowerContext 的 `src/`，
所以先执行自举脚本：

```bash
cd qoder
bash bootstrap.sh
```

它会做四件事：

1. **准备 PowerContext 源码**，按顺序取第一个可用来源：
   环境变量 `POWERCONTEXT_SRC` → 仓库同级 `../src/` → 已下载的 `.upstream/`
   → **本仓库 `2026-competition` 分支（`git archive` 取出，不需要外网）** → 上游浅克隆；
2. **建虚拟环境** `.venv`（有 `uv` 用 `uv venv --python 3.12`，否则 `python3 -m venv`）；
3. **安装依赖**：`powercontext[server]`、`pylibseekdb`、`aiomysql`、`pymysql<1.2.1`、`pytest`、`pyyaml`；
4. **自检**：打印各包版本并导入 `rca` 与 `powercontext.server.factory`。

`bash bootstrap.sh` 是幂等的，可以重复执行。

---

## 4 配置

```bash
cp .env.example .env      # 可选，不配置也能跑
```

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `POWERCONTEXT_PORT` | `8312` | PowerContext Server 端口 |
| `POWERCONTEXT_URL` | `http://127.0.0.1:8312` | Server 地址 |
| `DATABASE_KIND` | `seekdb` | `seekdb`（本题要求）或 `sqlite`（仅临时调试） |
| `POWERCONTEXT_SRC` | 自动准备 | PowerContext 源码目录 |

---

## 5 数据初始化与调用入口

### 5.1 导入语料

```bash
bash run.sh ingest                  # 导入 data/corpus 下的 .md/.txt
bash run.sh ingest path/to/papers   # 或指定自己的语料目录
```

文献切块后写入 seekdb 的 `rca_chunks` 表，每块记录 `chunk_id`、所属文献、段落号与内容 sha256。
每条执行的 SQL 都追加到 `logs/db-queries.jsonl`。

### 5.2 提问并生成带证据的报告

```bash
bash run.sh ask "如何降低嵌入式数据库中文档检索的延迟" \
  --aspects "索引结构,检索延迟预算,分布式部署,GPU 加速"
```

产出 `work/reports/<task_id>.md`，包含四段：

1. **结论与证据** —— 每个子问题下列出证据原文首句与 `[En]` 编号；
2. **证据缺口** —— 证据不足 / 单一 / 语料未覆盖的子问题；
3. **证据清单** —— `[En]` 对应的完整 `chunk_id` 与 64 位 `sha256`；
4. **可核验说明** —— 自检会做什么。

同时把报告写入 PowerContext Source，把任务状态写入 Memory。

### 5.3 状态复用

```bash
bash run.sh restart                 # 重启 Server，PID 变化
bash run.sh resume research-001     # 从 PowerContext 读回状态与报告，校验 sha256
bash run.sh ask "..." --task research-001   # 沿用同一任务，报告里带上「上次任务进展」
bash run.sh status                  # 列出所有研究任务
```

### 5.4 自检

```bash
bash run.sh verify     # 逐条回查证据 + 缺口数比对 + 报告 sha256 + 状态可读
bash run.sh test       # 单元测试
bash run.sh all        # 完整演示：reset -> ingest -> ask -> restart -> resume -> status -> verify
```

`verify` 会做这些事：

1. 解析报告里的每一个 `[En]`，逐条 `SELECT` 回 seekdb 读取证据块；
2. 比对 `sha256`、文献编号与原文片段是否与报告一致；
3. 比对「证据缺口」行数与任务状态里记录的缺口数量；
4. 从 PowerContext 回读报告，比对 `report_sha256`。

**任何一条对不上都会判定失败，不会静默通过。**

---

## 6 三种技术的分工

| 技术 | 在本项目里做什么 | 怎么核对 |
| --- | --- | --- |
| **seekdb**（embedded） | 存文献证据块与关键词；检索时把 `LIKE` 条件下推到 SQL 执行；报告中每条证据都从它读回 | `logs/db-queries.jsonl`、`bash run.sh verify` 的逐条回查 |
| **PowerContext** | 存研究任务状态（Memory）与报告正文（Source）；重启后读回复用 | `logs/restart.jsonl`、`work/*.state.json`、`bash run.sh resume` |
| **Qoder** | 完成全部编码、调试与测试，并通过 Qoder Sites 发布项目网站 | `docs/qoder-dev-log.md` |

---

## 7 产物位置

| 产物 | 路径 |
| --- | --- |
| 研究报告 | `work/reports/<task_id>.md` |
| 任务状态快照 | `work/<task_id>.state.json` |
| 数据库查询记录 | `logs/db-queries.jsonl` |
| Server 重启记录 | `logs/restart.jsonl` |
| Server 日志 | `logs/server.log` |
| seekdb 数据目录 | `data/seekdb/`（运行态，不入库） |
| PowerContext 数据 | `data/pc/`（运行态，不入库） |

---

## 8 已知限制

* **不调用大模型**：结论只来自检索到的原文，不做生成式改写。这是可核验的前提，
  也意味着它不会替你「总结成一段话」，而是把证据原文摆出来。
* **只支持 Markdown / 纯文本**：PDF 请先转成 Markdown 再入库。
* **中文按二元组匹配**：没有引入分词库，同义词改写（如「延迟」vs「时延」）召回会漏，
  需要人工在 `--aspects` 里覆盖常用说法。
* **检索是关键词 + 覆盖度**：未启用向量检索，语义相近但用词不同的段落可能召回不到。
* **单机单用户**：未做并发控制，多人同时写同一个 seekdb 数据目录会冲突。
* `pylibseekdb` 只有 Linux / macOS wheel，Windows 需 WSL 或 Docker。
* **在 WSL 里本地开发时多一步**：`/mnt/d` 是 drvfs 挂载，不支持 `fallocate`，seekdb 建库会失败。
  执行 `bash scripts/dev-setup-wsl.sh` 一次即可（它把 `RCA_SEEKDB_PATH` / `RCA_PC_HOME`
  写进 `.env`，把数据目录挪到 WSL 原生 ext4）。**评测环境是原生 Linux，不需要这一步。**
