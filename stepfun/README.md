# 端侧知识库 · seekdb 混合检索（阶跃星辰生态赛题）

在浏览器本地把文档编码成向量，再交给 seekdb 做向量 + 全文混合检索。
不调用任何云端推理 API，模型文件由本地服务托管，推理全程在用户设备上完成。

> 题面：端侧 AI 推理性能优化与 seekdb 混合检索
> 资产目录：`stepfun/` ｜ 分支：`2026-competition-ecosystem`

---

## 1 它能做什么

1. **导入**：把 `.md` / `.txt` 按段落切块，逐块在浏览器里生成向量（WebGPU 优先，不可用自动降级 WASM，界面实时显示当前后端）；
2. **写入**：向量、原文与元数据通过 seekdb-js 写入 seekdb 集合；
3. **检索**：输入查询，在本地生成查询向量，调用 seekdb 的 `hybridSearch`（向量 + 全文，RRF 融合）返回排序结果与原文；
4. **增量**：新导入的文档写入后即可被检索，集合与会话状态由 seekdb 维护。

---

## 2 快速开始

### 2.1 环境要求

| 项 | 版本 |
| --- | --- |
| 操作系统 | Linux（评测环境）或 WSL2 Ubuntu 22.04 |
| Node.js | ≥ 20（`seekdb` SDK 要求） |
| seekdb | 1.4.0（`seekdb` 命令行，随包提供 server 模式） |
| 浏览器 | Chrome / Edge 最新版（WebGPU 可选，不支持时自动降级 WASM） |

### 2.2 安装

```bash
cd stepfun

# 1) 启动 seekdb（默认 2881 端口；已有实例会跳过）
bash scripts/start-seekdb.sh

# 2) 安装依赖（约 1 分钟）
bash scripts/install-deps.sh

# 3) 下载 INT8 模型（约 23MB，走 hf-mirror）
bash scripts/download-model.sh
```

> `install-deps.sh` 处理了两个坑：`seekdb` 的 npm 包内部使用 `workspace:` 协议无法直接安装（改为从 tarball 手动装配）；`@huggingface/transformers` 的 `onnxruntime-node` 安装脚本要从 GitHub 下二进制（用 `--ignore-scripts` 跳过，浏览器只用 `onnxruntime-web`）。

### 2.3 启动

```bash
bash scripts/start.sh
# 打开 http://127.0.0.1:8090
```

也可以用 `npm start`（前提是 seekdb 已在运行）。

### 2.4 验证

页面右上角应显示：

- **后端**：`WebGPU（INT8）` 或 `WASM（INT8，已从 WebGPU 降级）`
- **数据库**：`seekdb · kb · N 块`

然后在左侧粘贴一段文本 → 点「切块 + 本地向量化 + 写入」→ 右侧输入查询 → 点「检索」。

完整步骤与预期结果见 [`docs/verification-sample.md`](docs/verification-sample.md)。

---

## 3 配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SEEKB_HOST` | `127.0.0.1` | seekdb 地址 |
| `SEEKB_PORT` | `2881` | seekdb 端口 |
| `SEEKB_USER` | `root` | 用户名 |
| `SEEKB_PASSWORD` | 空 | 密码 |
| `SEEKB_DATABASE` | `stepfun_kb` | 数据库（启动时自动创建） |
| `SEEKB_COLLECTION` | `kb` | 集合名 |
| `EMBED_DIM` | `384` | 向量维度，必须与模型一致 |
| `APP_PORT` | `8090` | Web 服务端口 |

配置示例不要写真实凭据。

---

## 4 数据流

```
浏览器
  文档 → 切块 → Transformers.js(WebGPU/WASM, INT8) → 向量(384d)
                                                    │ POST /api/documents
                                                    ▼
                                            server（Node）
                                                    │ seekdb-js add()
                                                    ▼
                                            seekdb 集合 kb
                                            （向量索引 + 全文索引）
                                                    ▲
  查询 → 本地向量化 ── POST /api/search ────────────┤ hybridSearch（RRF）
                                                    │
                          排序结果 + 原文 + 距离 ◀──┘
```

**检索完全在 seekdb 内完成**：应用只把查询向量与查询文本传过去，融合与排序由 `DBMS_HYBRID_SEARCH` 执行，客户端不分别取两路结果再拼。

---

## 5 目录结构

```
stepfun/
  server/
    index.js          HTTP 服务（静态页面 + API + vendor/models 托管）
    seekdb.js         seekdb 连接、集合管理、写入、混合检索
  web/
    index.html        界面
    app.js            本地推理、切块、向量化、调用 API
    style.css
  scripts/
    install-deps.sh   依赖安装（处理 workspace 协议与 onnxruntime-node 坑）
    start-seekdb.sh   启动 seekdb
    start.sh          一键启动
    download-model.sh 下载 INT8 ONNX 模型
    benchmark.sh      端到端性能测试
  models/             模型文件（不入库，由脚本下载）
  data/sample-docs/   示例语料（6 篇）
  docs/
    verification-sample.md  验证样例
    perf-report.md          性能与量化对比数据
  TECHNICAL-NOTE.md   一页技术说明
```

---

## 6 量化对比实验（可选）

主流程不依赖这一步；要复现技术说明里的体积与质量数据时执行：

```bash
# 需要 onnxruntime、tokenizers、numpy
pip install onnxruntime tokenizers numpy

# 下载 FP32 基线（约 90MB）
curl -fsSL "https://hf-mirror.com/Xenova/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx" \
  -o models/Xenova/all-MiniLM-L6-v2/onnx/model.onnx

python3 scripts/quant-compare.py
```

脚本会输出：两个模型的字节数、压缩比、文档/查询向量化耗时，以及 5 条查询在
18 个语料块上的 top-5 重合率（以 FP32 排序为基准）。实测结果见 `TECHNICAL-NOTE.md` 第 1 节。

## 7 已知限制

- **模型需单独下载**：`models/` 不入库（23MB），执行 `bash scripts/download-model.sh` 获取；离线环境可提前下载后放同一路径。
- **仅支持 Markdown / 纯文本**：PDF 需先转文本。
- **中文检索依赖二元组/分词**：全文索引用 seekdb 默认分词，中文短语命中率不如英文；查询词建议覆盖关键词。向量通道可缓解同义改写问题。
- **WebGPU 依赖浏览器与显卡**：不支持的设备会自动降级 WASM，功能不受影响，速度较慢。
- **单用户单实例**：未做并发写入控制。
- **seekdb 端口固定 2881**：与其它 seekdb 实例冲突时改 `SEEKB_PORT`。
