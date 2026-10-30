# Qoder 题 · 交接手册（给你看的操作步骤）

> 我已完成的部分：项目设计、接口骨架、示例语料、运行脚本、契约文档。
> 你要做的部分：在 Qoder 里把这些骨架实现出来、留下开发记录、发布站点。
> 这道题要求「主要开发工作必须在 Qoder 中完成」，所以核心编码必须由 Qoder 执行 —— 这正是下面的流程。

---

## 一、工作区怎么设置（你要做的第一件事）

### 1. 工作区路径

```
D:\hejixin\2026-2027\比赛\oceanbase数据库大赛\workspace\powercontext1\qoder
```

这个目录既是 Qoder 的工作区，也是最终要提交进仓库的 `qoder/` 目录 —— 不需要在别处再建一份。

### 2. 在 Qoder 桌面端打开

1. 打开 Qoder 桌面端，选「打开文件夹 / Open Folder」；
2. 选上面这个路径；
3. 打开后确认左侧文件树里能看到 `src/rca/`、`docs/DESIGN.md`、`data/corpus/`。

### 3. 运行环境说明（重要）

项目依赖 `pylibseekdb`（嵌入式 seekdb），它**只提供 Linux / macOS wheel**，
Windows 装不了。这台机器已经装好 WSL + Ubuntu-22.04，所以：

- **代码**放在 Windows 的这个目录里（Qoder 直接编辑）；
- **命令**全部在 WSL 里执行（路径是 `/mnt/d/hejixin/2026-2027/比赛/oceanbase数据库大赛/workspace/powercontext1/qoder`）。

我在 `qoder/AGENTS.md` 里写了这条规则，Qoder 打开工作区时会读到，
执行命令时会自动走 `wsl.exe`。如果它没遵守，你就手动在提示词里加一句：

> 所有 shell 命令都必须通过 `wsl.exe -u root -e bash -lc "..."` 执行，因为项目依赖 Linux-only 的 pylibseekdb。

### 4. 第一次跑通环境（先做这个，别急着写代码）

在 Qoder 里发这条：

> 请在 WSL 里执行 `cd /mnt/d/hejixin/2026-2027/比赛/oceanbase数据库大赛/workspace/powercontext1/qoder && bash bootstrap.sh`，
> 然后执行 `bash run.sh --help`，把输出贴给我。如果报错，按报错修到能跑。

`bootstrap.sh` 会准备 PowerContext 源码、建好 `.venv`、装依赖（首次需要联网）。
成功后你就有了可执行环境。

---

## 二、开发流程（分 7 步，每步都截图）

**不要一次把全部任务丢给 Qoder。** 题面要求开发记录能体现 Qoder 在「需求拆解、编码、调试」
各环节做了什么，分步做才有过程可记录。

每一步的操作：复制下面「给 Qoder 的提示词」→ 发给 Qoder → 等它做完 → 跑验收命令 → 截图。

### 步骤 0 · 需求拆解（先让 Qoder 读懂设计）

```
请阅读 qoder/docs/DESIGN.md 和 src/rca/ 下所有骨架代码，先不要改代码。
给我一份任务拆解：每个模块要做什么、依赖谁、按什么顺序实现、每一步怎么验证。
指出设计里你认为有风险或不清楚的地方。
```

**截图点**：Qoder 输出的任务拆解列表（这一步就是「需求拆解」环节的证据）。

### 步骤 1 · seekdb 连接与语料入库

```
按 DESIGN.md 任务 1 实现 store.py 的 open/close/replace_documents/stats 和 parser.py。
要求：
- 用 pylibseekdb.aopen + connection_options 的 unix_socket 交给 aiomysql；
- 扫描 data/corpus 下的 .md/.txt，跳过 README.md，按段落聚合切块（目标 480 字，重叠 12%）；
- 按 doc_id 覆盖写入，重复 ingest 不产生重复块；
- 每条 SQL 追加到 logs/db-queries.jsonl。
完成后在 WSL 里执行 bash run.sh ingest，把输出贴出来。
```

**验收**：`bash run.sh ingest` 打印 6 篇文献的块数；再执行一次，块数不变。
**截图点**：Qoder 的实现说明 + ingest 输出。

### 步骤 2 · 检索与打分

```
按 DESIGN.md 任务 2 实现 store.search 和 textutil.py。
要点：查询词构造 text LIKE 的 OR 条件下推到 seekdb，不要全表拉回内存；
中文用去虚词后的二元组，不要退化成单字匹配；first_sentence 只截取不改写。
完成后在 WSL 里写一段临时脚本验证：查「降低嵌入式数据库文档检索延迟」，
打印每个候选块的分数和 doc_id，确认不相关的块分数明显低。
```

**验收**：能看到相关块高分、无关块低分。
**截图点**：分数分布输出（这是「调试」环节的证据）。

### 步骤 3 · 证据选择与缺口判定

```
按 DESIGN.md 任务 3 实现 evidence.py。状态判定严格按 DESIGN 第 4.1 节，不要放宽阈值。
完成后执行：
bash run.sh ask "如何降低嵌入式数据库中文档检索的延迟" --aspects "索引结构,检索延迟预算,分布式部署,GPU 加速"
预期：前两个子问题 evidence 充分，后两个进缺口表。
把报告里「证据缺口」那一段贴出来。
```

**验收**：`分布式部署` 和 `GPU 加速` 必须出现在缺口表里。类型可能是「语料未覆盖」也可能是
「证据单一」（语料在「本文未覆盖…」声明里会提到这些词，字面命中是正常的）。
**截图点**：缺口表输出。这一步最能证明「证据边界」是真的在工作。

### 步骤 4 · 报告渲染

```
按 DESIGN.md 任务 4 实现 report.py。严格按第 5 节的章节顺序和表格列顺序，不要改标题。
证据清单必须写完整的 chunk_id 和完整 64 位 sha256。
完成后贴出 work/reports/research-001.md 的前 40 行和证据清单表的头 3 行。
```

**验收**：报告结构完整、证据行能被解析。
**截图点**：报告内容。

### 步骤 5 · PowerContext 状态存取与续研

```
按 DESIGN.md 任务 5 实现 state.py 和 cli.py 的 cmd_ask / cmd_status / cmd_resume。
完成后依次执行并贴出输出：
bash run.sh ask "..." --task research-001
bash run.sh restart
bash run.sh resume research-001
bash run.sh status
```

**验收**：重启后 `resume` 能读回状态与报告，sha256 校验通过；`ask --task` 的报告里有「上次任务进展」段。
**截图点**：restart + resume 的输出（这是「状态复用」的证据）。

### 步骤 6 · 可核验自检 + 测试

```
按 DESIGN.md 任务 6 实现 cli.py 的 cmd_verify，按任务 7 补 tests/。
完成后执行 bash run.sh verify 和 bash run.sh test，贴出输出。
然后做一次反向验证：把报告里某条证据的 sha256 故意改错一位，再跑 verify，确认它报失败。
```

**验收**：verify 全绿；改错 sha256 后必须报失败。
**截图点**：两次 verify 的输出对比（证明自检不是摆设）。

---

## 三、开发记录怎么整理

题面要「关键开发环节的 Qoder 对话截图或录屏，并附 Qoder 账号 UID」。

把截图按下面顺序命名，放到 `qoder/docs/screenshots/`（自己新建目录）：

```
01-需求拆解.png      步骤 0 的任务拆解输出
02-编码-入库.png     步骤 1
03-调试-打分.png     步骤 2 的分数分布
04-缺口判定.png      步骤 3 的缺口表
05-报告渲染.png      步骤 4
06-状态复用.png      步骤 5 的 restart + resume
07-自检.png          步骤 6 两次 verify
```

然后填 `qoder/docs/qoder-dev-log.md`（我已建好模板，把每步的时间、提示词摘要、Qoder 做了什么、遇到什么问题怎么修的填进去）。

**你的 Qoder 账号 UID**：`01a18c9f-2203-7b40-9ea8-97c4f33d52b3`
（已经记在 `qoder/docs/qoder-dev-log.md` 里了，提交时平台要填这个）

---

## 四、发布项目网站（Qoder Sites）

代码跑通后：

1. 在 Qoder 里打开 Sites 功能，新建站点；
2. 可见范围设置为「**任何人都可访问**」（个人账号才能设，你这个是个人版，没问题）；
3. 站点内容按 `qoder/docs/site-content.md` 里的文案填（我已经写好了项目简介、解决的问题、核心功能、技术分工）；
4. 需要补的图：跑通后的报告截图、缺口表截图、数据库查询记录截图；
5. 发布后把网址记下来，用**无痕窗口**打开确认未登录也能访问。

⚠️ 评审结束前不要暂停或删除站点；改内容后要再点一次「发布」才会更新线上版本。

---

## 五、提交材料清单

| 材料 | 从哪来 | 状态 |
| --- | --- | --- |
| 项目网站网址 | Qoder Sites 发布后 | 待你发布 |
| 代码仓库 | `https://github.com/Funnyvalentine00/powercontext1`，分支 `2026-competition-ecosystem` | 待提交 |
| 运行说明 | `qoder/README.md` | 已写 |
| 验证样例 | `qoder/docs/verification-sample.md` | 已写 |
| Qoder 开发记录 | `qoder/docs/qoder-dev-log.md` + 截图 | 模板已写，待你填 |
| Qoder 账号 UID | `01a18c9f-2203-7b40-9ea8-97c4f33d52b3` | 已记 |
| 技术使用记录 | `qoder/logs/` 下的运行日志、`db-queries.jsonl` | 跑通后自动生成 |

提交时平台填三项：**网站网址 + 代码仓库地址 + Qoder 账号 UID**。

---

## 六、注意事项

1. **不要提交真实凭据**。`.env` 已被 `.gitignore` 排除，配置示例用占位值。
2. **不要改契约**。`DESIGN.md` 里标了「契约」的表结构、章节标题、表格列顺序，改了会让自检失效。
3. **分层退出**。如果某一步 Qoder 卡住超过预期，停下来把报错贴给我，我帮你定位。
4. **先跑通再美化**。网站可以用 Qoder Sites 的模板，重点是把功能截图和证据放上去。
5. **建议顺序**：先做步骤 0~3（能出报告就够演示核心价值），再补 4~6，最后做站点。
