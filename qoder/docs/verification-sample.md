# 验证样例：从文献到可核验的研究报告

本文件是项目的验证样例，供评审按步骤复现。每条命令都在 `qoder/` 目录下执行。

---

## 1 这个样例要证明什么

| 要证明的 | 在哪一步 | 看什么 |
| --- | --- | --- |
| 项目能运行 | 步骤 1~3 | 命令有输出、报告能生成 |
| seekdb 实际参与 | 步骤 2、5 | `logs/db-queries.jsonl` 里的真实 SQL；verify 逐条回查证据 |
| 证据边界真的生效 | 步骤 3 | 报告里「证据缺口」表把没覆盖的子问题标出来 |
| PowerContext 实际参与 | 步骤 4 | 重启后 `resume` 读回状态与报告，sha256 一致 |

---

## 2 任务描述

| 项 | 内容 |
| --- | --- |
| 研究问题 | 如何降低嵌入式数据库中文档检索的延迟 |
| 子问题 1 | 索引结构（语料里有 2 篇以上涉及索引类型与压缩） |
| 子问题 2 | 检索延迟预算（语料里有 3 篇给出延迟数据） |
| 子问题 3 | 分布式部署（只在「本文未覆盖分布式…」这类声明里出现，应判缺口） |
| 子问题 4 | GPU 加速（语料未讨论 GPU，应判缺口） |
| 预期结果 | 前两个子问题给出带 `[En]` 的证据；后两个出现在「证据缺口」表里 |

任务为什么这样设计：如果系统对任何问题都给出「看起来很完整」的答案，就无法验证它是真的在检索。
故意放两个语料基本不覆盖的子问题，是为了让评审一眼看出「证据边界」是在工作，而不是在编答案。

> 后两个缺口的具体类型不固定：完全检索不到是「语料未覆盖」，只来自一篇文献是「证据单一」，
> 命中 1 条但不足 2 条是「证据不足」。三种都说明系统在如实标注边界。
> **本次实测是「证据不足」**：两个子问题各只命中 1 条证据，低于门槛的 2 条。

---

## 3 初始数据

| 数据 | 位置 | 说明 |
| --- | --- | --- |
| 示例语料 | `data/corpus/*.md` | 6 篇自造文献（非真实论文，数字为示例值） |
| 语料说明 | `data/corpus/README.md` | 说明这 6 篇覆盖什么、故意缺什么（该文件不入库） |
| seekdb 数据目录 | `data/seekdb/` | 由 `ingest` 首次运行时创建 |

替换成自己的语料：把 PDF 转成 Markdown 后放进 `data/corpus/`，删掉示例文件，
再执行 `bash run.sh ingest`。

---

## 4 操作步骤

### 步骤 1 · 准备环境

```bash
cd qoder
bash bootstrap.sh
```

预期：打印各依赖版本与 `PowerContext Server 依赖与 rca 包导入自检通过`。

### 步骤 2 · 语料入库

```bash
bash run.sh ingest
```

预期输出形如：

```
[ingest] 语料目录 .../qoder/data/corpus
[ingest] 6 篇文献，NN 个证据块已写入 seekdb .../qoder/data/seekdb
[ingest]   chunking-strategy -> N 块 · 文档分块策略对检索质量的影响
...
[ingest] seekdb 现有 6 篇文献 / NN 个证据块
```

再执行一次，块数不变（覆盖写入，不重复）。

### 步骤 3 · 提问并查看缺口

```bash
bash run.sh ask "如何降低嵌入式数据库中文档检索的延迟" \
  --aspects "索引结构,检索延迟预算,分布式部署,GPU 加速"
```

预期（本次实测）：

```
[ask] 1. 索引结构 -> supported（证据充分：4 条，文献 3 篇）
[ask] 2. 检索延迟预算 -> supported（证据充分：4 条，文献 3 篇）
[ask] 3. 分布式部署 -> insufficient（证据不足：1 条，文献 1 篇）
[ask] 4. GPU 加速 -> insufficient（证据不足：1 条，文献 1 篇）
[ask] 证据覆盖：0.5000
[ask] 证据缺口（2 个）：
```

报告路径 `work/reports/research-001.md`。

查看缺口段：

```bash
sed -n '/## 二、证据缺口/,/## 三、证据清单/p' work/reports/research-001.md
```

预期看到「分布式部署」「GPU 加速」两行，类型是「语料未覆盖」或「证据单一」。

### 步骤 4 · 重启后复用状态

```bash
bash run.sh restart
bash run.sh resume research-001
```

预期：

```
[restart] PID 1234 -> 5678；之后的 resume/verify 只依赖 PowerContext 中的状态
[resume] 从 PowerContext 读回任务 research-001（updated_at=...）
[resume] 子问题 4 个，证据 N 条，缺口 2 个
[resume]   缺口：分布式部署（证据不足）
[resume]   缺口：GPU 加速（证据不足）
[resume] 报告已从 PowerContext Source 回读，sha256 一致（...）
```

PID 必须变化，否则重启没有真正发生。

> 注意：在 WSL 里 PID 命名空间会重新计数，新 PID 可能小于旧 PID（例如 `3342 -> 394`）。
> 判断重启是否真的发生，依据是 PID 有变化 + `logs/restart.jsonl` 里的时间戳，而不是 PID 大小。

### 步骤 5 · 可核验自检

```bash
bash run.sh verify
```

预期：每条证据都「在 seekdb 中命中且 sha256 一致」，缺口数与状态一致，报告 sha256 一致，
最后一行 `[verify] 结果：全部通过`。

### 步骤 6 · 反向验证（证明自检不是摆设）

把报告里某条证据的 sha256 改错一位，再跑一次：

```bash
cp work/reports/research-001.md /tmp/report.bak
sed -i '0,/`[0-9a-f]\{64\}`/s//`0000000000000000000000000000000000000000000000000000000000000000`/' work/reports/research-001.md
bash run.sh verify          # 必须报失败
cp /tmp/report.bak work/reports/research-001.md
bash run.sh verify          # 恢复后重新通过
```

---

## 5 指定技术发挥作用的记录

### 5.1 seekdb

| 证据 | 位置 |
| --- | --- |
| 建表与入库的真实 SQL | `logs/db-queries.jsonl`（含 `CREATE TABLE rca_chunks`、`INSERT`、`DELETE`） |
| 检索时的下推查询 | 同文件里的 `SELECT ... WHERE text LIKE ... LIMIT 300` |
| 证据回查 | `bash run.sh verify` 输出的「N 条证据全部在 seekdb 中命中且 sha256 一致」 |
| 数据落盘 | `data/seekdb/` 目录 |

### 5.2 PowerContext

| 证据 | 位置 |
| --- | --- |
| 任务状态写入 | `work/research-001.state.json`（与 Memory 中的内容一致） |
| 报告写入 Source | `resume` 输出的 `报告已从 PowerContext Source 回读` |
| 重启记录 | `logs/restart.jsonl`（old_pid / new_pid） |
| 状态复用 | `resume` 与 `status` 的输出 |

---

## 6 重置方法

```bash
bash run.sh stop
bash run.sh reset
```

`reset` 会删除 `data/`（含 seekdb 数据目录）、`work/`、`logs/`，回到「从没运行过」的状态。
语料 `data/corpus/` 不受影响，可以反复重跑。

---

## 7 结果不一致时怎么排查

| 现象 | 排查方向 |
| --- | --- |
| `ingest` 报找不到 pylibseekdb | 没在 WSL 里执行，或 `bootstrap.sh` 没跑成功 |
| 报告里所有子问题都是 `missing` | 语料没入库（先跑 `ingest`），或 `MIN_SCORE` 被改高了 |
| 缺口数量与预期不同 | 检查是否把 `data/corpus/README.md` 也入了库（它提到了「分布式部署」，会污染判定） |
| 缺口表里缺失关键词出现「式部」这类不是词的片段 | 正常现象：中文按二元组切分，「分布式部署」会切出「分布/布式/式部/部署」，语料里没有连续的「式部」 |
| 「分布式部署」命中的证据是「本文未覆盖分布式分片场景」这种否定句 | 正常现象：关键词检索判不出否定语义，但正因为只有 1 条证据，系统判成了「证据不足」而不是当作充分证据 |
| `resume` 报没有任务状态 | `ask` 没成功执行，或 `reset` 之后没有重新跑 `ask` |
| `verify` 报证据不存在 | 重新 `ingest` 后块编号可能变化，需要重新 `ask` 生成报告 |
