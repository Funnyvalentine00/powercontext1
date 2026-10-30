# seekdb 数据库查询记录

- 后端：embedded seekdb (pylibseekdb)
- 数据目录：`/root/eval/repo/minimax/data/pc/seekdb`
- 数据库：`test`
- 采集时间：2026-10-30T21:39:10+0800
- 表总数：46；有数据的表：15；总行数：52

## 执行的 SQL

```sql
SHOW TABLES;
SELECT COUNT(*) FROM `pc_artifact_heads`;  -- rows=1
SELECT COUNT(*) FROM `pc_artifact_processing_intents`;  -- rows=4
SELECT COUNT(*) FROM `pc_artifact_processing_pending`;  -- rows=1
SELECT COUNT(*) FROM `pc_artifact_processing_schema`;  -- rows=1
SELECT COUNT(*) FROM `pc_artifact_processing_sequences`;  -- rows=1
SELECT COUNT(*) FROM `pc_artifacts`;  -- rows=9
SELECT COUNT(*) FROM `pc_memory_entry_heads`;  -- rows=9
SELECT COUNT(*) FROM `pc_memory_entry_versions`;  -- rows=9
SELECT COUNT(*) FROM `pc_recall_token_daily`;  -- rows=1
SELECT COUNT(*) FROM `pc_scope_creation_requests`;  -- rows=2
SELECT COUNT(*) FROM `pc_scope_settings`;  -- rows=1
SELECT COUNT(*) FROM `pc_scopes`;  -- rows=2
SELECT COUNT(*) FROM `pc_source_journal_heads`;  -- rows=1
SELECT COUNT(*) FROM `pc_sources`;  -- rows=9
SELECT COUNT(*) FROM `pc_topic_memory_retrieval_shape`;  -- rows=1
SELECT `text` FROM `pc_memory_entry_versions` WHERE `text` LIKE '%优惠不叠加%';  -- 命中 1 行
SELECT `searchable_text` FROM `pc_memory_entry_heads` WHERE `searchable_text` LIKE '%def compute_refund%';  -- 命中 1 行
SELECT `searchable_text` FROM `pc_memory_entry_heads` WHERE `searchable_text` LIKE '%def test_member_discount_not_stacked_with_threshold%';  -- 命中 1 行
SELECT `text` FROM `pc_memory_entry_versions` WHERE `text` LIKE '%minimax.sddsync.state.v1%';  -- 命中 1 行
SELECT `payload` FROM `pc_sources` WHERE `payload` LIKE '%powercontext.work-contract.v1%';  -- 命中 1 行
```

> 上表之外还对每张表的每个文本列执行过同样的 `LIKE` 探测；
> 完整语句清单（743 条）见 `queries.sql` 与 `inspect.json`。

## 表与行数

| 表 | 行数 | 文本列 |
| --- | --- | --- |
| `pc_agent_skill_targets` | 0 | `-` |
| `pc_artifact_candidate_heads` | 0 | `-` |
| `pc_artifact_candidate_versions` | 0 | `-` |
| `pc_artifact_heads` | 1 | `scope_id` |
| `pc_artifact_lineage_artifacts` | 0 | `-` |
| `pc_artifact_lineage_sources` | 0 | `-` |
| `pc_artifact_processing_auto_wave_targets` | 0 | `-` |
| `pc_artifact_processing_binding_states` | 0 | `-` |
| `pc_artifact_processing_intents` | 4 | `binding_name` |
| `pc_artifact_processing_leases` | 0 | `-` |
| `pc_artifact_processing_migration_receipts` | 0 | `-` |
| `pc_artifact_processing_pending` | 1 | `binding_name` |
| `pc_artifact_processing_schema` | 1 | `phase` |
| `pc_artifact_processing_sequences` | 1 | `-` |
| `pc_artifact_publications` | 0 | `-` |
| `pc_artifact_tags` | 0 | `-` |
| `pc_artifacts` | 9 | `scope_id` |
| `pc_connector_checkpoints` | 0 | `-` |
| `pc_dream_runs` | 0 | `-` |
| `pc_external_skill_registrations` | 0 | `-` |
| `pc_memory_entry_heads` | 9 | `scope_id` |
| `pc_memory_entry_versions` | 9 | `scope_id` |
| `pc_model_usage_daily` | 0 | `-` |
| `pc_profile_policies` | 0 | `-` |
| `pc_recall_token_daily` | 1 | `scope_id` |
| `pc_receipt_migration_review` | 0 | `-` |
| `pc_recurrence_match` | 0 | `-` |
| `pc_recurrence_observation` | 0 | `-` |
| `pc_scope_bindings` | 0 | `-` |
| `pc_scope_context_references` | 0 | `-` |
| `pc_scope_creation_requests` | 2 | `idempotency_key` |
| `pc_scope_external_references` | 0 | `-` |
| `pc_scope_settings` | 1 | `name` |
| `pc_scopes` | 2 | `scope_id` |
| `pc_skill_packages` | 0 | `-` |
| `pc_skill_publications` | 0 | `-` |
| `pc_source_cursors` | 0 | `-` |
| `pc_source_definition_manifests` | 0 | `-` |
| `pc_source_journal_heads` | 1 | `scope_id` |
| `pc_sources` | 9 | `scope_id` |
| `pc_topic_memory_active_chunks` | 0 | `-` |
| `pc_topic_memory_active_topics` | 0 | `-` |
| `pc_topic_memory_processing_targets` | 0 | `-` |
| `pc_topic_memory_retrieval_shape` | 1 | `shape` |
| `pc_topic_memory_revision_publications` | 0 | `-` |
| `pc_topic_memory_work_budgets` | 0 | `-` |

## 工程资料样本（有数据的表）

### `pc_artifact_heads`.`scope_id`

```text
scp_2wz6vgs302d6k7300rrybvt9na
```

### `pc_artifact_processing_intents`.`binding_name`

```text
experience-incubation
```

### `pc_artifact_processing_intents`.`binding_name`

```text
memory-source-window
```

### `pc_artifact_processing_pending`.`binding_name`

```text
topic-memory-source-window
```

### `pc_artifact_processing_schema`.`phase`

```text
complete
```

### `pc_artifacts`.`scope_id`

```text
scp_2wz6vgs302d6k7300rrybvt9na
```

### `pc_artifacts`.`scope_id`

```text
scp_2wz6vgs302d6k7300rrybvt9na
```

### `pc_memory_entry_heads`.`scope_id`

```text
scp_2wz6vgs302d6k7300rrybvt9na
```

### `pc_memory_entry_heads`.`scope_id`

```text
scp_2wz6vgs302d6k7300rrybvt9na
```

### `pc_memory_entry_versions`.`scope_id`

```text
scp_2wz6vgs302d6k7300rrybvt9na
```

### `pc_memory_entry_versions`.`scope_id`

```text
scp_2wz6vgs302d6k7300rrybvt9na
```

### `pc_recall_token_daily`.`scope_id`

```text
scp_2wz6vgs302d6k7300rrybvt9na
```

### `pc_scope_creation_requests`.`idempotency_key`

```text
minimax-sdd-task-001
```

### `pc_scope_creation_requests`.`idempotency_key`

```text
powercontext.default-scope.v1
```

### `pc_scope_settings`.`name`

```text
default
```

### `pc_scopes`.`scope_id`

```text
scp_2wz6vgs302d6k7300rrybvt9na
```

### `pc_scopes`.`scope_id`

```text
scp_761mhgjscyxpzdy3yjsvazv281
```

### `pc_source_journal_heads`.`scope_id`

```text
scp_2wz6vgs302d6k7300rrybvt9na
```

### `pc_sources`.`scope_id`

```text
scp_2wz6vgs302d6k7300rrybvt9na
```

### `pc_sources`.`scope_id`

```text
scp_2wz6vgs302d6k7300rrybvt9na
```

### `pc_topic_memory_retrieval_shape`.`shape`

```text
fts
```

## 关键证据检索（LIKE 命中）

| 证据 | 标记 | 表.列 | 片段 |
| --- | --- | --- | --- |
| 规格条款 | `优惠不叠加` | `pc_memory_entry_versions`.`text` | 计费规格（当前版本 v2）  版本：v2（2026-10-30）  ## R1 退款上限  单笔退款金额不得超过用户实付金额，结果保留两位小数。  ## R2 优惠不叠加  会员折扣（折扣率下限 0.80，即最多 8 折）与订单满减（满 100 元减 10 元）不得同时作用于同一笔退款。 当两种优惠条件都满足时，只允许 |
| 代码符号 | `def compute_refund` | `pc_memory_entry_heads`.`searchable_text` | reshold_amount return paid_amount return round paid_amount threshold_discount 2 def compute_refund order order float u_6309 u_89c4 u_683c u_8ba1 u_7b97 u_5e94 u |
| 测试用例 | `def test_member_discount_not_stacked_with_threshold` | `pc_memory_entry_heads`.`searchable_text` | b_4e00_79cd b_79cd_4f18 b_4f18_60e0 160 from refund import order compute_refund def test_member_discount_not_stacked_with_threshold order order paid_amount 200  |
| 任务状态 | `minimax.sddsync.state.v1` | `pc_memory_entry_versions`.`text` |  "5ed18f44f0ed2b0ee6406816e6b4845edcacbd7c7a8829a53cfe2e3a4eb5370a", "schema": "minimax.sddsync.state.v1", "scope_id": "scp_2wz6vgs302d6k7300rrybvt9na", "task_i |
| Work Contract | `powercontext.work-contract.v1` | `pc_sources`.`payload` | ext-source-v1","representation":"native","value":{"content":"{\n  \"schema\": \"powercontext.work-contract.v1\",\n  \"trust\": \"untrusted_input\",\n  \"objecti |

## Server 实际执行的 SQL（节选 60/400 条）

```sql
INFO sqlalchemy.engine.Engine SELECT DATABASE()
INFO sqlalchemy.engine.Engine SELECT @@sql_mode
INFO sqlalchemy.engine.Engine SELECT @@lower_case_table_names
INFO sqlalchemy.engine.Engine SELECT pc_artifact_processing_schema.singleton, pc_artifact_processing_schema.schema_version, pc_artifact_processing_schema.source_version, pc_artifact_processing_schema.phase, pc_artifact_processing_schema.migration_id, pc_artifact_processing_schema.config_manifest
INFO sqlalchemy.engine.Engine INSERT INTO pc_artifact_processing_schema (singleton, schema_version, source_version, phase, migration_id, config_manifest) VALUES (%s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE schema_version = pc_artifact_processing_schema.schema_version
INFO sqlalchemy.engine.Engine SELECT pc_artifact_processing_schema.singleton, pc_artifact_processing_schema.schema_version, pc_artifact_processing_schema.source_version, pc_artifact_processing_schema.phase, pc_artifact_processing_schema.migration_id, pc_artifact_processing_schema.config_manifest
INFO sqlalchemy.engine.Engine SELECT count(*) AS count_1
INFO sqlalchemy.engine.Engine SELECT count(*) AS count_1
INFO sqlalchemy.engine.Engine SELECT count(*) AS count_1
INFO sqlalchemy.engine.Engine SELECT count(*) AS count_1
INFO sqlalchemy.engine.Engine SELECT count(*) AS count_1
INFO sqlalchemy.engine.Engine SELECT count(*) AS count_1
INFO sqlalchemy.engine.Engine SELECT count(*) AS count_1
INFO sqlalchemy.engine.Engine SELECT count(*) AS count_1
INFO sqlalchemy.engine.Engine SELECT count(*) AS count_1
INFO sqlalchemy.engine.Engine UPDATE pc_artifact_processing_schema SET phase=%s WHERE pc_artifact_processing_schema.singleton = %s
INFO sqlalchemy.engine.Engine SELECT pc_artifact_processing_schema.singleton, pc_artifact_processing_schema.schema_version, pc_artifact_processing_schema.source_version, pc_artifact_processing_schema.phase, pc_artifact_processing_schema.migration_id, pc_artifact_processing_schema.config_manifest
INFO sqlalchemy.engine.Engine SELECT column_name, is_nullable FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = %s
INFO sqlalchemy.engine.Engine SELECT column_name, is_nullable FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = %s
INFO sqlalchemy.engine.Engine SELECT check_clause FROM information_schema.check_constraints WHERE constraint_schema = DATABASE() AND constraint_name = %s
INFO sqlalchemy.engine.Engine SELECT check_clause FROM information_schema.check_constraints WHERE constraint_schema = DATABASE() AND constraint_name = %s
INFO sqlalchemy.engine.Engine SELECT check_clause FROM information_schema.check_constraints WHERE constraint_schema = DATABASE() AND constraint_name = %s
INFO sqlalchemy.engine.Engine SELECT CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME = 'ck_pc_artifact_tags_family'
INFO sqlalchemy.engine.Engine SELECT column_name FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = %s
INFO sqlalchemy.engine.Engine SELECT column_name FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = %s
INFO sqlalchemy.engine.Engine SELECT column_name FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = %s
INFO sqlalchemy.engine.Engine SELECT pc_scopes.scope_id, pc_scopes.title, pc_scopes.summary
INFO sqlalchemy.engine.Engine SELECT pc_scope_external_references.scope_id, pc_scope_external_references.ordinal, pc_scope_external_references.value
INFO sqlalchemy.engine.Engine SELECT pc_scope_bindings.integration, pc_scope_bindings.kind, pc_scope_bindings.external_id
INFO sqlalchemy.engine.Engine SELECT pc_memory_entry_heads.entry_version_id
INFO sqlalchemy.engine.Engine SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'pc_artifact_heads' AND column_name = %s
INFO sqlalchemy.engine.Engine SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'pc_artifact_heads' AND column_name = %s
INFO sqlalchemy.engine.Engine SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'pc_artifact_heads' AND column_name = %s
INFO sqlalchemy.engine.Engine SELECT pc_artifact_heads.scope_id, pc_artifact_heads.artifact_id, pc_artifact_heads.revision, pc_artifacts.content
INFO sqlalchemy.engine.Engine SELECT pc_artifact_heads.scope_id, pc_artifact_heads.artifact_id, pc_artifact_heads.revision, pc_artifacts.content
INFO sqlalchemy.engine.Engine SELECT pc_artifact_heads.artifact_id
INFO sqlalchemy.engine.Engine SELECT pc_artifacts.scope_id, pc_artifacts.artifact_id, pc_artifacts.revision
INFO sqlalchemy.engine.Engine UPDATE pc_topic_memory_retrieval_shape SET shape=pc_topic_memory_retrieval_shape.shape WHERE pc_topic_memory_retrieval_shape.singleton = %s
INFO sqlalchemy.engine.Engine SELECT pc_topic_memory_retrieval_shape.shape, pc_topic_memory_retrieval_shape.profile_fingerprint
INFO sqlalchemy.engine.Engine SELECT count(*) AS count_1
INFO sqlalchemy.engine.Engine SELECT pc_topic_memory_retrieval_shape.shape, pc_topic_memory_retrieval_shape.profile_fingerprint
INFO sqlalchemy.engine.Engine SELECT pc_topic_memory_active_topics.artifact_id
INFO sqlalchemy.engine.Engine SELECT pc_topic_memory_active_topics.scope_id, pc_topic_memory_active_topics.artifact_id, pc_topic_memory_active_topics.revision
INFO sqlalchemy.engine.Engine SELECT pc_topic_memory_active_chunks.scope_id, pc_topic_memory_active_chunks.artifact_id, pc_topic_memory_active_chunks.revision, pc_topic_memory_active_chunks.chunk_ordinal
INFO sqlalchemy.engine.Engine SELECT pc_artifact_heads.scope_id, pc_artifact_heads.artifact_id, pc_artifact_heads.revision, pc_topic_memory_active_topics.revision AS active_revision
INFO sqlalchemy.engine.Engine SELECT pc_scope_settings.scope_id
INFO sqlalchemy.engine.Engine SELECT pc_scope_creation_requests.request_digest, pc_scope_creation_requests.scope_id
INFO sqlalchemy.engine.Engine INSERT INTO pc_scopes (scope_id, title, summary, scope_id_search, title_search, summary_search, parent_scope_id, version) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
INFO sqlalchemy.engine.Engine DELETE FROM pc_scope_context_references WHERE pc_scope_context_references.scope_id = %s
INFO sqlalchemy.engine.Engine DELETE FROM pc_scope_external_references WHERE pc_scope_external_references.scope_id = %s
INFO sqlalchemy.engine.Engine INSERT INTO pc_scope_creation_requests (idempotency_key, request_digest, scope_id) VALUES (%s, %s, %s)
INFO sqlalchemy.engine.Engine SELECT pc_scopes.scope_id, pc_scopes.title, pc_scopes.summary, pc_scopes.scope_id_search, pc_scopes.title_search, pc_scopes.summary_search, pc_scopes.parent_scope_id, pc_scopes.version
INFO sqlalchemy.engine.Engine SELECT pc_scope_context_references.scope_id, pc_scope_context_references.referenced_scope_id
INFO sqlalchemy.engine.Engine SELECT pc_scope_external_references.scope_id, pc_scope_external_references.kind, pc_scope_external_references.value
INFO sqlalchemy.engine.Engine SELECT pc_scopes.scope_id, pc_scopes.title, pc_scopes.summary, pc_scopes.scope_id_search, pc_scopes.title_search, pc_scopes.summary_search, pc_scopes.parent_scope_id, pc_scopes.version
INFO sqlalchemy.engine.Engine SELECT pc_scope_context_references.scope_id, pc_scope_context_references.referenced_scope_id
INFO sqlalchemy.engine.Engine SELECT pc_scope_external_references.scope_id, pc_scope_external_references.kind, pc_scope_external_references.value
INFO sqlalchemy.engine.Engine UPDATE pc_scope_settings SET scope_id=%s WHERE pc_scope_settings.name = %s
INFO sqlalchemy.engine.Engine INSERT INTO pc_scope_settings (name, scope_id) VALUES (%s, %s)
INFO sqlalchemy.engine.Engine SELECT 1
```

> 完整清单见同目录 `queries.sql`。
