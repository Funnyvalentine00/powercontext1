# AGENTS.md —— 在本目录工作的 AI agent 请遵守

## 运行环境

代码在 Windows 目录 `...\workspace\powercontext1\qoder` 下编辑，
但项目依赖 `pylibseekdb`（**只提供 Linux / macOS wheel**），所以**所有命令必须在 WSL 里执行**。

命令模板：

```bash
wsl.exe -u root -e bash -lc "cd '/mnt/d/hejixin/2026-2027/比赛/oceanbase数据库大赛/workspace/powercontext1/qoder' && <你的命令>"
```

不要尝试在 Windows 的 PowerShell 里 `pip install pylibseekdb`，装不上。

## 项目契约（不要修改）

- `docs/DESIGN.md` 第 3 节的数据表结构、第 3.2 节的状态字段名；
- `docs/DESIGN.md` 第 5 节的报告章节标题与证据清单表格列顺序（`verify` 依赖它解析）；
- `src/rca/pc_client.py` 已完整可用，不需要重写；
- `src/rca/cli.py` 里的 `load_settings` / `start_server` / `stop_server` / `restart_server` 已可用，不需要重写。

## 任务从哪来

按 `docs/DESIGN.md` 第 6 节的任务 1~7 顺序实现。每个任务都写了「完成判据」，做完先跑判据再进入下一个。

## 验收命令

```bash
bash bootstrap.sh                                            # 首次准备环境
bash run.sh ingest                                           # 语料入库
bash run.sh ask "研究问题" --aspects "子问题1,子问题2"
bash run.sh restart && bash run.sh resume research-001       # 状态复用
bash run.sh verify                                           # 可核验自检
bash run.sh test                                             # 单元测试
```

## 代码风格

- Python 3.11+，PEP 8，行宽 120；
- 注释用中文，解释「为什么」而不是「做了什么」；
- 不引入 `requirements.txt` 之外的依赖；
- 异常要带上下文信息，不要吞掉错误。

## 禁止事项

- 不要调用大模型生成报告结论（报告必须是可回溯的原文证据）；
- 不要为了让测试通过而放宽 `MIN_SCORE` / `MIN_EVIDENCE` / `MIN_DOCUMENTS`；
- 不要把 seekdb 换成 sqlite（sqlite 只用于非 Linux 环境的临时调试，不能作为交付路径）。
