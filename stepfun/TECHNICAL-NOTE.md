# 一页技术说明：端侧知识库（seekdb × 阶跃星辰）

## 1 模型与量化

| 项 | 内容 |
| --- | --- |
| 模型 | `Xenova/all-MiniLM-L6-v2`（源模型 `sentence-transformers/all-MiniLM-L6-v2`，MIT） |
| 来源 | hf-mirror 镜像的同名仓库，由 `scripts/download-model.sh` 下载到 `models/` |
| 向量维度 | 384 |
| 量化方式 | **INT8**：使用仓库自带的 `onnx/model_quantized.onnx`（dynamic quantization，权重 8 位、激活浮点） |
| FP32 基线 | 同仓库 `onnx/model.onnx` |

**体积与压缩比（实测）**

| 精度 | 文件 | 字节 | 压缩比 |
| --- | --- | ---: | ---: |
| FP32 | `model.onnx` | 90,387,606（86.2 MiB） | 1.00x |
| INT8 | `model_quantized.onnx` | 22,972,370（21.9 MiB） | **3.94x** |

**检索质量变化（实测）**

方法：6 篇示例语料切出 18 个块，构造 5 条查询，分别用 FP32 与 INT8 生成向量，
以余弦相似度排序，比较各自 top-5 的重合情况（以 FP32 排序为基准）。

| 指标 | 结果 |
| --- | --- |
| top-5 重合率（平均） | **0.96** |
| 逐查询 | `1.0 / 0.8 / 1.0 / 1.0 / 1.0` |
| 结论 | 只有 1 条查询的第 2、3 名顺序互换，命中集合未变 |

复跑方式：`python3 scripts/quant-compare.py`（需 onnxruntime + tokenizers，见 README）。

**推理耗时（CPU，onnxruntime，同一批数据）**

| 阶段 | FP32 | INT8 | 提速 |
| --- | ---: | ---: | ---: |
| 18 个块的向量化 | 0.376 s | 0.253 s | 33% |
| 5 条查询的向量化 | 0.095 s | 0.056 s | 41% |

## 2 端侧运行

| 项 | 实现 |
| --- | --- |
| 运行时 | Transformers.js 4.3.2（内置 onnxruntime-web） |
| 后端选择 | `web/app.js` 的 `initModel()` 先尝试 `device: 'webgpu'`，抛错则用 `device: 'wasm'` |
| 界面提示 | 右上角后端徽章显示 `WebGPU（INT8）` 或 `WASM（INT8，已从 WebGPU 降级）` |
| 精度 | `dtype: 'q8'`（INT8） |
| 模型加载 | 本地托管：`allowRemoteModels=false`、`localModelPath='/models/'`，由 server 提供 `/models/*` |
| 无云端推理 | 浏览器只访问本机 `/models/`、`/vendor/`、`/api/*`，无外部推理请求 |

**实测（Chrome，WebGPU 可用）**：模型加载 1597 ms，页面显示 `WebGPU（INT8）`。

**降级验证**：在禁用 WebGPU 的设备/浏览器上，`pipeline` 首次初始化抛出异常，
代码捕获后改用 WASM，徽章显示降级提示，核心流程不受影响。

## 3 seekdb 使用

| 项 | 内容 |
| --- | --- |
| 版本 | seekdb 1.4.0.0（server 模式，端口 2881） |
| SDK | `seekdb@1.4.0`（npm），经 `mysql2` 连接 |
| 数据库/集合 | `stepfun_kb` / `kb`（启动时自动建库） |
| 集合结构 | `Schema` + `VectorIndexConfig(hnsw, dimension=384)`，全文索引默认开启；`embeddingFunction=null`（向量由浏览器生成，服务端不做嵌入） |
| 写入 | `collection.add({ ids, documents, embeddings, metadatas })`，元数据含文档名、段落序号 |
| 混合检索 | `collection.hybridSearch({ query: { whereDocument }, knn: { queryEmbeddings, queryTexts }, rank: { rrf } })` —— 融合与排序由 seekdb 执行，客户端不做两路拼合 |
| 增量与刷新 | 新块写入后立即可检索；集合与会话状态由 seekdb 维护 |

## 4 状态与优化

| 优化点 | 做法 |
| --- | --- |
| 批处理 | 文档向量化按每批 8 块调用 `pipeline`，减少单次调用开销 |
| 模型本地化 | 模型由服务端托管，浏览器不依赖外网，避免跨域与网络策略问题 |
| 分阶段计时 | 界面显示模型加载、文档向量化、写入、查询向量化、seekdb 检索五段耗时 |
| 前端切块 | 段落边界优先、目标 400 字，减少块数从而降低向量化次数 |

**已知成本**：向量随每次写入上传（384 维 float32 约 1.5KB/块）；语料规模大时应改为分批写入。

## 5 与题面要求的对应

| 要求 | 落点 |
| --- | --- |
| 浏览器本地向量化 | `web/app.js` 的 `embed()`；模型与推理都在浏览器 |
| INT8/FP16 量化 + 体积与质量对比 | 本文第 1 节（实测） |
| WebGPU 优先、WASM 降级并提示 | `initModel()` + 后端徽章 |
| seekdb 存向量/原文/元数据 | `server/seekdb.js` 的 `addChunks` |
| 混合检索由 seekdb 完成 | `hybridSearch` 单次调用 |
| 增量写入与刷新可检索 | 步骤 4（验证样例） |
| 性能优化前后实测 | 第 1 节耗时表 + 界面分阶段计时 |
