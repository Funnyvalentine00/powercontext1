# 研究问题：如何降低嵌入式数据库中文档检索的延迟

> 任务编号：research-001 ｜ 生成时间：2026-10-31T00:15:25+08:00 ｜ 语料规模：6 篇文献 / 12 个块 ｜ 证据覆盖：50% ｜ 证据总数：8

## 一、结论与证据

### 1. 索引结构

状态：`OK`，证据 4 条，文献 3 篇

- 在嵌入式数据库中引入向量检索，最大的约束不是算力，而是常驻内存。 [E1]
  - 出处：`轻量级向量索引结构在嵌入式数据库中的实现` 第 1 段，块编号 `lightweight-vector-index-c000`，匹配度 1.00
- 常见的重叠比例是 10% 到 20%。 [E2]
  - 出处：`文档分块策略对检索质量的影响` 第 2 段，块编号 `chunking-strategy-c001`，匹配度 0.72
- 嵌入式数据库受限于内存，倒排索引的存储效率直接决定能索引多少文档。 [E3]
  - 出处：`倒排索引压缩与查询加速` 第 1 段，块编号 `inverted-index-compression-c000`，匹配度 0.50
- 位图在高频词上优势明显，但词表规模大时预处理成本高。 [E4]
  - 出处：`倒排索引压缩与查询加速` 第 2 段，块编号 `inverted-index-compression-c001`，匹配度 0.38

### 2. 检索延迟预算

状态：`OK`，证据 4 条，文献 3 篇

- 在 Agent 工作流里，检索往往被调用多次。 [E5]
  - 出处：`Agent 场景下的检索延迟预算` 第 1 段，块编号 `latency-budget-agent-c000`，匹配度 1.00
- 慢档：查跨文档聚合与去重，目标 60ms，只在最终报告阶段执行。 [E6]
  - 出处：`Agent 场景下的检索延迟预算` 第 2 段，块编号 `latency-budget-agent-c001`，匹配度 0.89
- 常见的重叠比例是 10% 到 20%。 [E2]
  - 出处：`文档分块策略对检索质量的影响` 第 2 段，块编号 `chunking-strategy-c001`，匹配度 0.72
- 单一向量检索在专有名词、编号、代码标识符上表现不佳，单一全文检索则对同义改写不敏感。 [E7]
  - 出处：`嵌入式数据库中的向量与全文混合检索` 第 1 段，块编号 `hybrid-retrieval-embedded-c000`，匹配度 0.63

### 3. 分布式部署

状态：`WARN`，证据 1 条，文献 1 篇

- 在内存最紧张的场景下，标量量化的常驻内存最小； [E8]
  - 出处：`轻量级向量索引结构在嵌入式数据库中的实现` 第 2 段，块编号 `lightweight-vector-index-c001`，匹配度 0.75

### 4. GPU 加速

状态：`WARN`，证据 1 条，文献 1 篇

- 嵌入式数据库受限于内存，倒排索引的存储效率直接决定能索引多少文档。 [E3]
  - 出处：`倒排索引压缩与查询加速` 第 1 段，块编号 `inverted-index-compression-c000`，匹配度 0.50

## 二、证据缺口

| 子问题 | 缺口类型 | 说明 | 缺失关键词 |
| --- | --- | --- | --- |
| 分布式部署 | insufficient（证据不足） | 仅 1 条证据，少于 2 条 | 式部 |
| GPU 加速 | insufficient（证据不足） | 仅 1 条证据，少于 2 条 | gpu |

## 三、证据清单

| 编号 | 文献 | 段落 | 块编号 | sha256 | 原文片段 |
| --- | --- | --- | --- | --- | --- |
| E1 | `lightweight-vector-index` | 1 | `lightweight-vector-index-c000` | `0cd2e9c57c37f48c5847d6efc3a891a2f4ad7ead3b57b9be3e210827e5344c0e` | 在嵌入式数据库中引入向量检索，最大的约束不是算力，而是常驻内存。 |
| E2 | `chunking-strategy` | 2 | `chunking-strategy-c001` | `159975f2889367408318fde3d6897d4f414a013d7f666aacf21a51eeaf7b11e0` | 常见的重叠比例是 10% 到 20%。 |
| E3 | `inverted-index-compression` | 1 | `inverted-index-compression-c000` | `1b217b188f2a4c8f90e0dd6c2665eff6326ecbe16f102c29aefd6a50f93add56` | 嵌入式数据库受限于内存，倒排索引的存储效率直接决定能索引多少文档。 |
| E4 | `inverted-index-compression` | 2 | `inverted-index-compression-c001` | `d070634e758fecd9c3ce9a17c8ddf4b87c520ca02e2197c05dfcf65abcefc4e4` | 位图在高频词上优势明显，但词表规模大时预处理成本高。 |
| E5 | `latency-budget-agent` | 1 | `latency-budget-agent-c000` | `86b1a2e73e3eb8fa46189b7ccd26b1e7ca962c79075f94e10be6236c809fcc3b` | 在 Agent 工作流里，检索往往被调用多次。 |
| E6 | `latency-budget-agent` | 2 | `latency-budget-agent-c001` | `3e557b732dd12ab2aa341fa85f9c44fbbb63a8c267010d5c7238899fffb460c3` | 慢档：查跨文档聚合与去重，目标 60ms，只在最终报告阶段执行。 |
| E7 | `hybrid-retrieval-embedded` | 1 | `hybrid-retrieval-embedded-c000` | `7c2b8ea6623b5e1428aeb2dc82818796ad1bdc70eb2216c2f1ba5a21946a28f2` | 单一向量检索在专有名词、编号、代码标识符上表现不佳，单一全文检索则对同义改写不敏感。 |
| E8 | `lightweight-vector-index` | 2 | `lightweight-vector-index-c001` | `3ad2ec28eb316dcd564cd43cd3e39a9f8027618e4995d90311d4de0882003da3` | 在内存最紧张的场景下，标量量化的常驻内存最小； |

## 四、可核验说明

本报告不调用大模型生成结论：结论区的每条内容都是证据块原文的首句截取，未改写、未补充推测。
证据清单给出完整 chunk_id 与完整 64 位 sha256；`bash run.sh verify` 会逐条回查 seekdb 的 `rca_chunks` 表并比对哈希。
若某条证据的 sha256 与库中记录不一致，说明报告被改动或语料已更新，该条结论应视为失效。
