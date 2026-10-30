# 验证样例：从本地向量化到 seekdb 混合检索

按下面的步骤可以完整走一遍「导入 → 本地向量化 → 写入 seekdb → 混合检索」。

## 1 初始条件

| 项 | 要求 |
| --- | --- |
| seekdb | 已启动，端口 2881（`bash scripts/start-seekdb.sh`） |
| 依赖 | 已执行 `bash scripts/install-deps.sh` |
| 模型 | 已执行 `bash scripts/download-model.sh`（23MB INT8） |
| 应用 | 已执行 `bash scripts/start.sh`，浏览器打开 `http://127.0.0.1:8090` |
| 初始数据 | 知识库为空（右上角显示 `seekdb · kb · 0 块`），或先点「清空知识库」 |

## 2 操作步骤

### 步骤 1 · 确认后端与数据库

打开页面后观察右上角两个徽章：

| 徽章 | 预期 |
| --- | --- |
| 后端 | `WebGPU（INT8）`（不支持 WebGPU 的设备显示 `WASM（INT8，已从 WebGPU 降级）`） |
| 数据库 | `seekdb · kb · 0 块` |

**核对点**：后端徽章必须明确标出当前使用的推理后端与精度。

### 步骤 2 · 导入语料

在左侧文本框粘贴：

```
倒排索引压缩可以显著降低查询延迟。Agent 场景应设定任务级延迟预算。文档分块建议段落边界优先。
```

点「切块 + 本地向量化 + 写入」。进度区会依次显示「正在处理 … i/N 块」→「完成：写入 N 块」。

**核对点**：

- 向量化发生在浏览器（DevTools 里看不到任何云端推理请求）；
- 写入完成后右上角块数增加。

也可以用文件选择器导入 `data/sample-docs/` 里的 6 篇示例文档，一次导入多篇。

### 步骤 3 · 检索

在右侧查询框输入 `延迟`，点「检索」。

预期返回若干结果卡片，每张包含：

- 文档名与段落序号
- 与查询的距离值
- 原文片段

**核对点**：含「延迟」的段落排在前面。

### 步骤 4 · 增量导入可检索

再粘贴一段新内容（例如 `向量索引在 1GB 内存下应优先考虑标量量化。`），重新点写入，然后查询 `量化`。

**核对点**：新导入的内容出现在结果里，无需重启服务。

### 步骤 5 · 清空

点「清空知识库」，右上角回到 `0 块`，重复步骤 2~3 可重新验证。

## 3 指定技术发挥作用的记录

### seekdb

| 证据 | 位置 |
| --- | --- |
| 集合与向量/全文索引创建 | `server/seekdb.js` 的 `ensureCollection`（`Schema` + `VectorIndexConfig`，维度 384） |
| 写入的向量、原文、元数据 | seekdb 库 `stepfun_kb` 的集合 `kb` |
| 混合检索在数据库内执行 | `server/seekdb.js` 的 `hybridSearch` 调用 `collection.hybridSearch`（`query.whereDocument` + `knn.queryEmbeddings` + `rank.rrf`） |
| 检索耗时 | 接口返回的 `elapsedMs` 字段（右栏「seekdb 检索」一栏） |

核对命令（可直接在 seekdb 里查）：

```bash
# 查看集合元数据表
mysql -h127.0.0.1 -P2881 -uroot -e "SHOW TABLES FROM stepfun_kb"
```

### 端侧推理

| 证据 | 位置 |
| --- | --- |
| 模型来源与精度 | 页面底部标注 `all-MiniLM-L6-v2（INT8）`；`web/app.js` 的 `MODEL_ID` / `DTYPE` |
| 推理后端选择 | 后端徽章；`web/app.js` 的 `initModel`（先 `device: 'webgpu'`，失败再 `device: 'wasm'`） |
| 无云端推理 | 浏览器 DevTools 网络面板只有 `/models/`、`/vendor/` 本地请求与 `/api/*` 本机请求 |

## 4 如何恢复初始状态

```bash
# 只清数据，保留模型与依赖
curl -s -X POST http://127.0.0.1:8090/api/reset
```

或在页面点「清空知识库」。

如需彻底重置 seekdb：

```bash
systemctl restart seekdb
curl -s -X POST http://127.0.0.1:8090/api/reset
```

## 5 常见问题

| 现象 | 排查 |
| --- | --- |
| 后端徽章一直「加载模型…」 | 检查 `models/Xenova/all-MiniLM-L6-v2/` 下是否有 `config.json`、`tokenizer.json`、`onnx/model_quantized.onnx` |
| 后端显示「模型加载失败」 | 先执行 `bash scripts/download-model.sh`；再看控制台是否报 `both local and remote models are disabled`（说明 `allowLocalModels` 未开启） |
| 数据库徽章显示错误 | 确认 seekdb 在 2881 运行（`bash scripts/start-seekdb.sh`） |
| 写入报「向量维度不正确」 | 模型维度必须为 384，与 `EMBED_DIM` 一致 |
| 检索无结果 | 先确认知识库块数大于 0；查询词换成语料里出现过的词 |
