# 设计说明（给 Qoder 的需求规格）

> 这份文档是项目的施工图：接口、数据模型、判定规则、报告格式和验收标准都定在这里。
> `src/rca/` 下已有骨架代码（函数签名 + docstring + TODO），实现由 Qoder 完成。
> 不要改动下面标了「契约」的字段名、表结构、章节标题和表格列顺序。

---

## 1 项目要解决什么

科研时读了几十篇论文，结论记不住、引用找不到源头、换台机器或隔几天就接不上。

这个工具做三件事：

1. **入库**：把文献切成证据块，存进 seekdb，每块带内容哈希；
2. **提问**：给一个研究问题，检索证据，产出**每句话都能回到原文**的报告；
3. **认边界**：证据不够的地方明确写「证据缺口」，不编造结论；
4. **接得上**：任务状态存进 PowerContext，重启后接着上次继续。

核心设计取舍：**不调用大模型生成结论**。结论一律是被检索到的原文片段，
所以每条都能按编号回到数据库核对。这让「可核验」成为产品特性，而不是一句口号。

---

## 2 模块与职责

```
src/rca/
  cli.py        命令入口（环境准备已可用，业务命令待实现）
  parser.py     语料扫描与分块
  store.py      seekdb 连接、入库、检索
  textutil.py   中英混合分词与匹配打分
  evidence.py   子问题拆分、证据选择、缺口判定
  report.py     报告渲染与解析
  state.py      PowerContext 任务状态与报告存取
  pc_client.py  PowerContext HTTP 客户端（已完整可用，不需要重写）
```

数据流：

```
语料 .md/.txt
   │ parser.load_documents + build_chunks
   ▼
seekdb.rca_chunks ──store.search──▶ 候选块
                                     │ textutil.score
                                     ▼
                               evidence.select_for_aspect
                                     │
                          ┌──────────┴──────────┐
                          ▼                     ▼
                    report.render_report    state.save_state
                          │                     │
                  work/reports/*.md      PowerContext Memory
                          │                     │
                  PowerContext Source     cli.resume 复用
```

---

## 3 数据模型（契约）

### 3.1 seekdb 表 `rca_chunks`

```sql
CREATE TABLE IF NOT EXISTS `rca_chunks` (
  `chunk_id` VARCHAR(80) NOT NULL,   -- 形如 lightweight-vector-index-c003
  `doc_id`   VARCHAR(80) NOT NULL,   -- 文件名主干
  `doc_title` VARCHAR(255) NOT NULL, -- 首个 Markdown 标题
  `seq`      INT NOT NULL,           -- 块序号，从 0 开始
  `text`     TEXT NOT NULL,          -- 块原文
  `keywords` VARCHAR(512),           -- 空格分隔的关键词，供 LIKE 检索
  `sha256`   VARCHAR(64) NOT NULL,   -- 块原文的 sha256
  PRIMARY KEY (`chunk_id`)
)
```

### 3.2 PowerContext 任务状态 `rca.task-state.v1`

字段：`schema / task_id / question / aspects / statuses / evidence / gaps /
documents / report_source_id / report_sha256 / chunk_stats / updated_at`。

- `evidence` 每项只存 `ref / chunk_id / doc_id / sha256`，完整原文留在 seekdb；
- 整个状态序列化后必须小于 8192 字节（Memory entry 上限）。

### 3.3 报告 Source 编号

`rca:report:{task_id}:{报告 sha256 前 16 位}` —— 报告内容一变，编号就变，
旧编号自然失效，不会出现「拿旧报告冒充新报告」。

---

## 4 判定规则（不要自行放宽）

### 4.1 证据状态

| status | 条件 | 含义 |
| --- | --- | --- |
| `supported` | 证据 ≥ 2 条且来自 ≥ 2 篇文献 | 证据充分 |
| `insufficient` | 证据 ≥ 1 条但不足 2 条 | 证据不足 |
| `single_doc` | 证据 ≥ 2 条但只来自 1 篇文献 | 证据单一 |
| `missing` | 没有分数达标的证据 | 语料未覆盖 |

阈值：单条证据的匹配分 ≥ `MIN_SCORE = 0.30`，每个子问题最多取 `TOP_K_PER_ASPECT = 4` 条。

### 4.2 打分

中文不引入分词库，用「去虚词字后的二元组」+ 英文/数字词做集合匹配。
覆盖度为主，同一词在块内重复出现给小权重加成。**不允许**退化成单字匹配，
单字区分度太低，会让任何含「数」「据」的块都被判为相关。

---

## 5 报告格式（契约）

章节顺序固定：

```
# 研究问题：<问题>
（概述：任务编号 / 生成时间 / 语料规模 / 证据覆盖 / 证据总数）

## 一、结论与证据
### 1. <子问题>
状态：`OK`/`WARN`/`GAP` + 证据条数 + 文献数
- <证据原文首句> [E1]
  - 出处：`<doc_title>` 第 N 段，块编号 `<chunk_id>`，匹配度 0.xx
...

## 二、证据缺口
| 子问题 | 缺口类型 | 说明 | 缺失关键词 |

## 三、证据清单
| 编号 | 文献 | 段落 | 块编号 | sha256 | 原文片段 |
| E1 | `doc_id` | 3 | `chunk-c003` | `64位完整sha256` | 原文片段 |

## 四、可核验说明
```

硬性要求：

1. 结论只能是证据原文，不得改写、不得补充推测；
2. 每条结论必须带 `[En]`，且编号在证据清单里有对应行；
3. 证据清单必须写**完整 chunk_id 与完整 64 位 sha256**（`verify` 靠它回查）；
4. 没有证据的子问题写「不给出结论」，不能编一段话填坑。

---

## 6 实现任务清单

按顺序做，每个任务做完都能跑起来看效果。

### 任务 1 · seekdb 连接与语料入库

文件：`store.py`（open / close / replace_documents / stats）、`parser.py`

要实现：

- `pylibseekdb.aopen(path)` 启动嵌入式实例，`connection_options()` 取 `unix_socket` 交给 `aiomysql.connect`；
- 连接后执行 DDL，重复执行不报错；
- 扫描 `data/corpus/` 的 `.md/.txt`，跳过 `README.md`，按段落聚合切块（目标 480 字，重叠 12%）；
- 按 doc_id 覆盖写入（先 DELETE 再 INSERT），保证重复 ingest 不会产生重复块；
- 每条 SQL 追加到 `logs/db-queries.jsonl`（JSONL：`{"ts","sql","params"}`）。

完成判据：`bash run.sh ingest` 打印每篇文献的块数；重复执行两次块数不变。

### 任务 2 · 检索与打分

文件：`store.py`（search）、`textutil.py`

要实现：

- 把查询词构造成 `text LIKE %词%` 的 OR 条件，下推到 seekdb 执行（不要全表拉回内存再过滤）；
- 只取前 16 个查询词，`LIMIT 300` 控制候选规模；
- `tokens()` / `coverage()` / `score()` / `keywords_of()` / `first_sentence()` 按第 4.2 节实现；
- `first_sentence()` 只做截取，不改写原文。

完成判据：对「降低嵌入式数据库文档检索延迟」能召回多篇文献的块，不相关块分数明显偏低。

### 任务 3 · 证据选择与缺口判定

文件：`evidence.py`

要实现：

- `split_aspects()`：显式 `--aspects` 优先，否则按 `，；。？！` 拆分，拆不出就整体一个；
- `EvidenceBook.register()`：同一个 chunk 复用编号，分数取最高；
- `select_for_aspect()`：按第 4.1 节判 status；
- `detect_gaps()`：非 supported 的子问题转缺口，`missing_terms` 取语料里完全没出现的查询词；
- `coverage_ratio()`：supported 占比。

完成判据：默认演示的 4 个子问题里，「索引结构」「检索延迟预算」判为 `supported`，
「分布式部署」「GPU 加速」必须出现在缺口表里。

注意：后两个的类型可能是 `missing`、`single_doc` 或 `insufficient` —— 语料在「本文未覆盖…」这类
声明里会提到这些词（例如「未覆盖分布式分片场景」含「分布式」），字面命中是正常现象。
「分布式部署」与「GPU 加速」各只命中 1 条证据，按 4.1 规则判 `insufficient` 是正确结果。
**不要**为了让它们变成 `missing` 去删改语料或调低阈值。

### 任务 4 · 报告渲染

文件：`report.py`

要实现 `render_report()` 与三个解析函数。严格按第 5 节格式。

完成判据：`work/reports/research-001.md` 能被 `parse_evidence_rows()` 解析出全部证据行，
且解析出的 sha256 与 seekdb 中的 `rca_chunks.sha256` 一致。

### 任务 5 · PowerContext 状态存取与续研

文件：`state.py`、`cli.py`（`cmd_ask` / `cmd_status` / `cmd_resume`）

要实现：

- `cmd_ask`：检索 → 选证据 → 判缺口 → 渲染 → 写 `work/reports/<task_id>.md`
  → 报告写入 PowerContext Source → 状态写入 Memory；
- `cmd_status`：列出 Memory 里所有 `research-state`，打印任务/子问题/证据/缺口数；
- `cmd_resume`：从 Memory 读状态、从 Source 回读报告、比对 sha256 后展示，并提示如何续研；
- `cmd_ask --task <id>`：报告里额外插入「## 零、上次任务进展（从 PowerContext 复用）」段落，
  列出上次的子问题、证据数与遗留缺口。

完成判据：`bash run.sh restart` 后执行 `bash run.sh resume research-001` 能读回状态与报告，
且 sha256 校验通过。

### 任务 6 · 可核验自检

文件：`cli.py`（`cmd_verify`）

要实现：对 `work/reports/` 下每份报告

1. 解析证据行，逐条 `store.get_chunk()` 回查，比对 sha256；
2. 报告缺口行数 vs 任务状态里的 `gaps` 数量；
3. 从 PowerContext 回读报告，比对 `report_sha256`；
4. 任何一项不通过就判定失败并打印具体原因。

完成判据：`bash run.sh verify` 全部通过；故意把某条证据的 sha256 改错，必须报失败。

### 任务 7 · 测试

文件：`tests/test_evidence.py`、`tests/test_parser.py`

至少覆盖：分块不丢内容、打分对相关/不相关块有区分度、四个 status 判定、
证据编号复用、报告解析往返（render → parse 得到同样的证据行）。

`bash run.sh test` 应能跑通。

---

## 7 非目标

- 不接大模型生成结论（保持可核验）；
- 不做 Web 前端（Qoder Sites 只做展示页，不放运行时）；
- 不做 PDF 解析（语料统一用 Markdown，PDF 转 Markdown 留给用户用工具处理）；
- 不做向量检索（本轮用关键词 + 覆盖度，向量作为后续扩展方向写进文档即可）。

---

## 8 分工说明（写进报告和站点都要用）

| 技术 | 在本项目里做什么 | 怎么核对 |
| --- | --- | --- |
| seekdb | 存文献证据块与关键词，检索时用 SQL 下推查询；报告里每条证据都从它读回 | `logs/db-queries.jsonl`、`store.get_chunk()` 回查 |
| PowerContext | 存研究任务状态与报告正文，重启后读回复用 | `logs/restart.jsonl`、`work/*.state.json`、`resume` 输出 |
| Qoder | 完成上述全部编码、调试与测试，并通过 Qoder Sites 发布项目网站 | `docs/qoder-dev-log.md` 的对话记录 |

---

## 9 实现决策补充

Qoder 在需求拆解阶段提出了 10 条风险。下面逐条给出决策，**实现时直接按这里做，不要再自行选择**。

### 9.1 中文虚词表（照抄这份）

```python
STOP_CHARS = set("的了是在和与或对及把被从到有为以这那个之而其所以可在不没很更最再又还就能会要")
```

不要删掉「数」「据」「检」「索」「库」这类实词字——它们是主题词的一部分。
这份表已写在 `textutil.py` 的骨架里，直接用。

### 9.2 打分公式（照抄这个）

```
coverage = |查询词 ∩ 文本词| / |查询词|
repeated = 查询词中在文本内出现 ≥ 2 次的个数
score = min(1.0, coverage + 0.15 * repeated / |查询词|)
```

不要把系数调大到 0.3 以上：那会让长块仅凭「同一个词出现多次」就越过 0.30 阈值。
阈值 `MIN_SCORE = 0.30` 不要动。

### 9.3 LIKE 检索的性能边界

当前语料 6 篇、总块数不到 100，`LIKE '%词%'` 全表扫描完全可接受。
**不要**为此引入向量检索、额外索引表或内存缓存。这个限制已写进 `README.md` 的「已知限制」，
评审看的是功能正确性，不是检索吞吐。

### 9.4 状态超过 8192 字节时的裁剪顺序

按顺序裁剪，**不要**直接抛错：

1. 先丢掉 `status == "missing"` 的子问题的 evidence（它们本来就没有证据）；
2. 再按 `score` 升序丢弃 evidence，但每个子问题至少保留 1 条；
3. 仍然超限才抛 `ValueError`。

`gaps` 与 `question` 永远不裁，它们是续研必需的信息。

### 9.5 seekdb 实例的生命周期

- `open()` 里把 instance / connection / cursor 三个对象都保存到 `self._*` 字段，防止被 GC 回收；
- `close()` 按 `cursor → connection → instance` 顺序关闭，每一步用 `try/except` 兜底；
- 所有命令都以 `async with SeekdbStore(...)` 的形式使用，**不要跨命令复用实例**。

### 9.6 报告表格必须转义

渲染任何表格单元格时：

- 把 `|` 替换为 `\|`；
- 把换行替换为空格；
- 把 sha256 放在反引号里（`parse_evidence_rows` 的正则依赖反引号定位）。

解析侧不做反转义——`parse_evidence_rows` 只取前 5 列，片段列不参与解析。

### 9.7 路径不需要转换（对风险 10 的纠正）

所有命令都在 WSL 里执行，此时 `Path(__file__).resolve()` 得到的已经是
`/mnt/d/hejixin/...` 这样的 Linux 路径，**不需要** Windows → Linux 路径转换，也不要写转换函数。

防御做法：在 `store.open()` 里检查 `str(self.path)` 是否以 `/` 开头，
不是就直接抛错「必须在 WSL 中运行」。这一行比写一套转换逻辑更可靠。

### 9.8 块数不足时补语料，不要降阈值

先跑 `bash run.sh ingest` 看实际块数。如果本该 `supported` 的子问题被判成 `insufficient`，
说明证据块太少。处理顺序：

1. 往 `data/corpus/` 补 1~2 篇相关文档，重新 `ingest`；
2. 仍不足才考虑调整 `--aspects` 的措辞，让子问题用词和语料更接近；
3. **禁止**降低 `MIN_SCORE` / `MIN_EVIDENCE` / `MIN_DOCUMENTS`。

### 9.9 verify 与 seekdb 重启的关系

`verify` 内部自建 store 实例读证据，与 `ask` 时的实例无关；
`restart` 重启的是 PowerContext Server，不动 seekdb 数据目录 `data/seekdb/`。

`verify` 开头应先确认 `data/seekdb/` 存在且非空，不存在就直接报错提示先跑 `ingest`，
避免出现「证据查不到」的误导性失败。

### 9.10 测试与实现同步

每实现一个模块就补对应测试，不要留到最后统一补。
至少保证 `tests/test_contract.py` 始终通过（它保护契约不被改坏）。

### 9.11 reset 只清运行态，绝不动语料（交付级契约）

`cmd_reset` 只能删除这几样：

- `data/seekdb/`（seekdb 数据目录）
- `data/pc/`（PowerContext 数据目录）
- `data/server.pid`
- `work/`、`logs/`

**禁止** `rmtree(data)` —— `data/corpus/` 就在 `data/` 下面，是整个作品的输入语料。
`bash run.sh all` 的第一步就是 `reset`，一旦误删，评审的全流程第一步就失败。

完成判据：

```bash
bash run.sh reset && ls data/corpus | wc -l    # 必须仍然输出 7（6 篇文献 + README）
bash run.sh all                                # 必须能完整跑完
```

### 9.12 本地 WSL 的 seekdb 存储位置（环境限制，不是代码问题）

`/mnt/d` 是 WSL 的 drvfs 挂载，**不支持 `fallocate`**；seekdb 建库需要写 32MB 的块文件，
会返回 `EOPNOTSUPP`。这是环境限制，与代码无关。

**不要用 bind-mount**（实测跨 `wsl.exe` 会话不保持）。改用环境变量把数据目录挪到原生 ext4：

```bash
bash scripts/dev-setup-wsl.sh      # 建目录并把两行配置写进 .env（幂等）
```

它会往 `.env`（已被 `.gitignore` 排除）写入：

```
RCA_SEEKDB_PATH=/var/lib/rca/seekdb
RCA_PC_HOME=/var/lib/rca/pc
```

`cli.load_settings()` 已支持这两个覆盖项，`cli.SEEKDB_PATH` 与 `cli.PC_HOME` 会在读取 `.env` 后更新。
所有命令都应通过 `cli.SEEKDB_PATH` / `cli.PC_HOME` 取路径（**不要**直接用 `DATA_DIR / "seekdb"`）。

- 评测环境是原生 Linux，不设置这两个变量，走的仍是 `data/seekdb` 与 `data/pc`；
- 代码里**不要**加「检测到 /mnt 就换目录」的逻辑；
- `SeekdbStore.open()` 捕获启动失败时，报错信息应附带一句
  「若在 WSL 的 /mnt/d 下运行，请先执行 bash scripts/dev-setup-wsl.sh」。

### 9.13 新增 `search` 子命令（检索对照演示）

用整句提问时，查询词有十几个，任意块至少命中一个，所以 12 个块会被全部召回。
评审看 `logs/db-queries.jsonl` 容易误以为「等于全表扫描」。需要一个能证明检索真在过滤的对照入口。

新增命令：

```bash
bash run.sh search "预算"
bash run.sh search "索引 结构"
```

要求：

- 参数是一个或多个关键词（空格或逗号分隔均可）；
- **只做检索与打分**，不写报告、不写 PowerContext 状态、不占任务编号；
- 输出必须包含：查询词个数、召回块数 / 语料总块数、每条块的分数与 `chunk_id`；
- 复用 `textutil.tokens` / `store.search` / `textutil.score`，不要另写一套检索逻辑；
- 退出码 0；没有任何召回时也正常退出，打印「0 条召回」。

完成判据：

```bash
bash run.sh search "预算"
```

召回的块数必须显著少于总块数（预期 2~4 个），且每一条召回块原文里都真的含「预算」。
把它写进 `docs/verification-sample.md` 的「指定技术发挥作用的记录」一节，作为检索下推的对照证据。

### 9.14 证据摘要的取句规则（修报告观感）

首版报告的结论区出现了这些内容：

```
- # 轻量级向量索引结构在嵌入式数据库中的实现 [E1]
- 8MB | 5ms | 12ms | [E4]
- ，目标 15ms，用于生成带引用的候选证据； [E6]
- 量做精排。 [E8]
```

分别对应：Markdown 标题行、表格行碎片、从句子中间截断的半句（重叠造成的）。
评审第一眼看的就是这一节，必须修。

`textutil.first_sentence()` 必须按顺序跳过：

1. 空行；
2. 以 `#` 开头的标题行；
3. 以 `|` 开头的表格行；
4. 长度小于 12 个字符的行（多半是重叠带来的半句）；
5. 以标点开头的行（`，。；！？、：,.;!?`），说明这句从中间被截断。

然后在剩余文本里取第一个以 `。` / `；` / `！` / `？` 结尾、且长度不超过 limit 的完整句。
整块找不到这样的句子时，退回取前 limit 个字符加省略号；最终仍为空则用块标题兜底，
**不允许返回空字符串**。

同时修两个显示问题：

- 「第 N 段」和证据清单表的「段落」列都改成 **1-based**（`seq + 1`），
  现在写的是「第 0 段」和 `0`，违反阅读直觉；
- 概述里的覆盖率显示成百分比（`50%`），不要写成 `0.5000`。

完成判据：重新生成报告后，结论区每一条都是完整可读的句子，
不再出现标题行、表格碎片或以标点/半句开头的内容。

