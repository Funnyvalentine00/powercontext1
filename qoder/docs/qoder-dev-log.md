# Qoder 开发记录

> 这份记录是本题「Qoder 开发可核对」的凭据，由参赛者填写。
> 每完成一个环节，就把时间、提示词摘要、Qoder 做了什么、遇到的问题与修法填进对应行，
> 并把截图放进 `docs/screenshots/`。

## 基本信息

| 项 | 值 |
| --- | --- |
| Qoder 账号 UID | `01a18c9f-2203-7b40-9ea8-97c4f33d52b3` |
| 账号类型 | 个人版（Qoder CN，已领取 2000 Credits） |
| 使用形态 | Qoder 桌面端 |
| 项目工作区 | `workspace/powercontext1/qoder` |
| 项目网站 | （Qoder Sites 发布后填写完整网址） |

## 一、需求拆解

| 项 | 内容 |
| --- | --- |
| 时间 | 2026-10-30 22:00 — 22:31 |
| 提示词摘要 | 让 Qoder 阅读 `docs/DESIGN.md` 与 `src/rca/` 骨架，产出任务拆解与风险点 |
| Qoder 的产出 | 模块依赖图（textutil → parser → store → evidence → report → state → cli）；7 个任务的实现顺序与验证方式表；10 条风险与不清楚的地方（虚词表、打分公式、LIKE 性能、8192 上界、实例生命周期、表格转义、路径转换、块数不足、verify 与重启、测试同步） |
| 截图 | `docs/screenshots/01-需求拆解.png` |

## 二、编码与调试

按 `docs/DESIGN.md` 任务 1~7 逐项填写。每一行都要有：Qoder 做了什么、跑什么命令验证、结果如何。

### 任务 1 · seekdb 连接与语料入库

| 项 | 内容 |
| --- | --- |
| 时间 | 2026-10-30 22:10 — 22:55 |
| 提示词摘要 | 按 DESIGN 任务 1 实现 parser + store；先跑 bootstrap；完成后跑 ingest 贴块数 |
| Qoder 的实现要点 | 扫描 6 篇语料（跳过 README）；段落聚合切块（目标 480 字 / 12% 重叠）；按 doc_id 覆盖写入；每条 SQL 落 `logs/db-queries.jsonl` |
| 验证命令与结果 | `bash run.sh ingest` → 6 篇 × 2 块 = 12 块；重复执行块数不变 |
| 遇到的问题与修法 | ① heredoc 反引号被外层 bash 吃掉 → 改临时脚本验证；② `/mnt/d` 是 drvfs 不支持 fallocate → 数据目录改到 WSL 原生 ext4（DESIGN 9.12）；③ `cmd_reset` 误删 `data/corpus` → 改为只清运行态（DESIGN 9.11）；④ `main()` 统一传参但五个零参命令不接受 → 补 `arguments` 参数（骨架自带 bug，由 Qoder 定位并修复） |
| 截图 | `docs/screenshots/02-编码-入库.png` |

### 任务 2 · 检索与打分

| 项 | 内容 |
| --- | --- |
| 时间 | 2026-10-30 23:00 — 23:18 |
| 提示词摘要 | 按 DESIGN 任务 2 实现 textutil 打分与 store.search |
| Qoder 的实现要点 | 照 9.1 虚词表；tokens = 英文词 + 中文二元组（不退化成单字）；score 严格按 9.2 公式；`search` 用 `text LIKE` 前 16 个查询词、`LIMIT 300`；`keywords` 按词频前 40 写入 |
| 验证命令与结果 | 12 候选块 / 6 篇全召回；相关块 0.494–0.744，无关块 0.125–0.134；`bash run.sh test` 23 项全过 |
| 遇到的问题与修法 | 无报错。主动预警 `latency-budget-agent-c000` 用整句打分只有 0.269（低于阈值），待任务 3 用短子问题复核 |
| 截图 | `docs/screenshots/03-调试-打分.png` |

### 任务 3 · 证据选择与缺口判定

| 项 | 内容 |
| --- | --- |
| 时间 | 2026-10-30 23:20 — 23:33 |
| 提示词摘要 | 按 DESIGN 任务 3 实现 evidence.py，并把 ask 跑到「status + 缺口表」这一步 |
| Qoder 的实现要点 | `split_aspects`（显式优先、按标点兜底）；`EvidenceBook` 同 chunk 复用编号并取最高分；`select_for_aspect` 四态判定；`detect_gaps` 映射缺口类型与缺失关键词；`coverage_ratio` |
| 验证命令与结果 | 4 子问题：索引结构 supported（4 条 / 3 篇）、检索延迟预算 supported（4 条 / 3 篇）、分布式部署 insufficient（1 条）、GPU 加速 insufficient（1 条）；覆盖率 50%，缺口 2 个；`bash run.sh test` 34 项全过 |
| 遇到的问题与修法 | 后两个判成 `insufficient` 而非预期的 `missing`：各只有 1 个块过阈值。按 4.1 规则这正是正确结果，未动阈值、未改语料 |
| 截图 | `docs/screenshots/04-缺口判定.png` |

### 任务 4 · 报告渲染

| 项 | 内容 |
| --- | --- |
| 时间 | 2026-10-30 23:34 — 23:47 |
| 提示词摘要 | 按 DESIGN 任务 4 实现 `render_report` 与三个解析函数 |
| Qoder 的实现要点 | 四段固定结构；证据清单写完整 chunk_id 与 64 位 sha256；表格单元格里的竖线做转义；结论只取证据原文首句，不改写、不补推测 |
| 验证命令与结果 | 生成 `work/reports/research-001.md`；解析出的 8 条 sha256 与 seekdb 全部一致；`bash run.sh test` 40 项全过 |
| 遇到的问题与修法 | 首版结论区出现表格碎片 `8MB ... 5ms ... 12ms`、从中间截断的短句、重叠带出的半句 → 按 DESIGN 9.14 重写 `first_sentence` 的跳过规则（标题行 / 表格行 / 短行 / 标点开头）；同时把段落编号改 1-based、覆盖率改百分比 |
| 截图 | `docs/screenshots/05-报告渲染.png` |

### 任务 5 · PowerContext 状态存取与续研

| 项 | 内容 |
| --- | --- |
| 时间 | 2026-10-30 23:48 — 2026-10-31 00:01 |
| 提示词摘要 | 按 DESIGN 任务 5 实现 state.py 与 `cmd_ask` / `cmd_status` / `cmd_resume`；顺手去掉 E6 的列表前缀 |
| Qoder 的实现要点 | 报告写入 PowerContext Source（编号含内容 sha 前 16 位）；任务状态写入 Memory（不超过 8192 字节，超限按 9.4 裁剪）；`cmd_resume` 从 Memory 读状态、从 Source 回读报告并校验 sha256；`--task` 复用生成「零、上次任务进展」段 |
| 验证命令与结果 | `restart` PID 3342→394（WSL 里 PID 重新计数）；`resume` 读回 4 个子问题状态、8 条证据、2 个缺口，报告 sha256 校验通过；`status` 列出 1 个任务；状态快照写入 `work/research-001.state.json` |
| 遇到的问题与修法 | verification-sample 承诺的 `work/<task_id>.state.json` 未生成 → 补 `json.dump` 快照（仅供人读，恢复仍只走 PowerContext） |
| 截图 | `docs/screenshots/06-状态复用.png` |

### 任务 6 · 可核验自检

| 项 | 内容 |
| --- | --- |
| 时间 | 2026-10-31 00:02 — 00:15 |
| 提示词摘要 | 按 DESIGN 任务 6 实现 `cmd_verify`，并做反向验证 |
| Qoder 的实现要点 | 开头校验 seekdb 数据目录非空；逐条 `get_chunk` 回查 8 条证据比对 sha256；缺口行数 vs 状态 gaps；从 PowerContext 回读报告比对 report_sha256；任一不通过打印 FAIL 并返回非零 |
| 验证命令与结果 | 正常 PASS（exit_code=0）；把 E1 的 sha256 改成 64 个 0 → FAIL 并精确指出 `E1（lightweight-vector-index-c000）sha256 不一致：报告 0000000000000000…，库中 0cd2e9c57c3…`（exit_code=1）；恢复后重新 PASS |
| 遇到的问题与修法 | 无 |
| 截图 | `docs/screenshots/07-自检.png` |

### 任务 7 · 单元测试

| 项 | 内容 |
| --- | --- |
| 时间 | 贯穿任务 1~6 |
| 提示词摘要 | 每实现一个模块同步补测试（DESIGN 9.10） |
| Qoder 的实现要点 | `tests/test_contract.py`（骨架阶段就有，保护契约）、`test_parser.py`、`test_textutil.py`、`test_evidence.py`、`test_report.py` |
| 验证命令与结果 | `bash run.sh test` → 50 passed |
| 遇到的问题与修法 | 无；每完成一个任务补一组，最后统一回归 |

## 三、站点发布

| 项 | 内容 |
| --- | --- |
| 时间 | 2026-10-31 |
| Qoder Sites 操作 | 新建站点 → 填 `docs/site-content.md` 的内容 → 可见范围设为「任何人都可访问」 → 发布 |
| 网站网址 | https://research-context-assistant-upqhrgcb0bf.qoder.zone/ |
| 无痕窗口验证 | 是（未登录状态下可正常打开） |
| 截图 | `docs/screenshots/08-站点发布.png` |

## 四、Qoder 在项目中承担了什么（小结）

Qoder 把 DESIGN 转成模块依赖图和 7 个带验收判据的任务，并主动列出 10 条风险，我据此补写了 DESIGN 第 9 节的实现决策。编码由它完成 `src/rca/` 下 7 个模块与 5 组测试（共 50 项）。调试中它定位出 seekdb 在 WSL 的 `/mnt/d` 上因 drvfs 不支持 fallocate 而启动失败，发现并修复 `main()` 统一传参导致零参命令抛 TypeError 的骨架 bug；报告首版结论区出现表格碎片，按 9.14 规则重写取句逻辑后修复。站点由 Qoder Sites 发布。
