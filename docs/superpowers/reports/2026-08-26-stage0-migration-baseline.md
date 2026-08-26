# 阶段0：数据库迁移基线验证报告（2026-08-26）

> 交接来源：`docs/CLAUDE_UPGRADE_HANDOFF.md` 阶段0
> 仓库：`E:\qiuzhaoxiangmu\zhishu-nexus`（分支 main，HEAD 3c7145e）

## 结论

✅ 空库迁移基线验证通过。全部 12 个迁移 + 2 个种子可从全新空 PostgreSQL 依次执行成功，
`migrate.py` 内置 delivery verification（`verify_delivery.sql`）通过；新增数据集表结构与全部约束正确；
重复执行幂等（`applied=0 skipped=14`）。

## 环境与方法

- 独立容器 `zhn-phase0-pg`（镜像 `pgvector/pgvector:pg16`，端口 `5544`，独立卷 `zhn-phase0_data`）。
- 凭据复用仓库 `.env`（POSTGRES_DB/USER/PASSWORD），密码未输出。
- 未触碰任何现有数据卷（含 `retail-analytics-agent_postgres_data`）与现有运行容器。
- 迁移执行：仓库 `.venv` + `PYTHONPATH=src`，`POSTGRES_PORT=5544` 覆盖默认 5432。

## 命令

```bash
# 启动空库（独立容器/卷/端口，不挂 initdb，保证 DB 为空）
cd /e/qiuzhaoxiangmu/zhishu-nexus
DB=$(grep '^POSTGRES_DB=' .env | cut -d= -f2 | tr -d '\r')
USER=$(grep '^POSTGRES_USER=' .env | cut -d= -f2 | tr -d '\r')
PASS=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2 | tr -d '\r')
docker run -d --name zhn-phase0-pg \
  -e POSTGRES_DB="$DB" -e POSTGRES_USER="$USER" -e POSTGRES_PASSWORD="$PASS" \
  -p 5544:5432 -v zhn-phase0_data:/var/lib/postgresql/data \
  pgvector/pgvector:pg16

# 确认空库
docker exec zhn-phase0-pg pg_isready -U "$USER" -d "$DB"
# -> public 表数量为 0

# 执行全部迁移 + 种子 + verify
PYTHONPATH=src POSTGRES_PORT=5544 ./.venv/Scripts/python.exe -m retail_analytics_agent.migrate
```

## 关键输出

### migrate 首次执行

```
applied=14 skipped=0
applied: 001_initial_schema.sql
applied: 002_query_audit_logs.sql
applied: 003_knowledge_chunks.sql
applied: 004_query_approval_logs.sql
applied: 005_resilience_and_idempotency.sql
applied: 006_execution_trace.sql
applied: 007_admin_read_models.sql
applied: 008_agent_context.sql
applied: 009_workspace_conversations.sql
applied: 010_agent_request_runs.sql
applied: 011_dataset_registry.sql
applied: 012_dataset_mapping.sql
applied: seed:001_demo_data.sql
applied: seed:002_richer_demo_dataset.sql
```

### migrate 幂等复跑

```
applied=0 skipped=14
```

### 表 / 列 / 数据验证

| 检查 | 结果 |
|---|---|
| public 表数量 | 16 |
| `dataset_registry` / `dataset_quality_reports` | 存在 |
| `dataset_registry.mapping` / `mapping_confirmed` | jsonb / boolean |
| `schema_migrations` 记录数 | 14 |
| `orders` 条数 / 渠道数 | 130 / 4（与 verify_delivery `>=130` 断言一致） |
| `dataset_registry` 行数 | 0（新建空表） |

### `dataset_registry` 约束

```
dataset_registry_pkey           PRIMARY KEY (dataset_id, version)
dataset_source_type_valid        CHECK source_type IN (postgres, csv, parquet)
dataset_status_valid             CHECK status IN (uploaded, profiling, needs_mapping, ready, failed, archived)
dataset_version_positive         CHECK version >= 1
dataset_row_count_non_negative   CHECK row_count >= 0
dataset_schema_name_safe         CHECK schema_name ~ '^staging_[a-z0-9_]+$'
dataset_quality_report_object    CHECK quality_report IS NULL OR jsonb_typeof = 'object'
dataset_mapping_object           CHECK mapping IS NULL OR jsonb_typeof = 'object'
```

### 其他 verification 脚本

| 脚本 | 结果 |
|---|---|
| `verify_delivery.sql`（migrate.py 内置） | ✅ |
| `verify_w2_1.sql` | ✅ `W2-1 database verification passed` |
| `verify_w4_1_metrics.sql` | ❌ 见已知边界 |

## 已知边界与说明

- `verify_w4_1_metrics.sql` 是早期里程碑（W4-1）对当时特定数据集的硬编码指标断言
  （paid 订单 5 个 / sales_amount 32900.00），与当前 richer demo 种子（130 订单 /
  实际 sales_amount 313098.00）不匹配，属**历史口径**，不代表迁移失败。
  `migrate.py` 约定只挂 `verify_delivery.sql`，与仓库现有行为一致。
- 阶段0 未修改任何源码或测试，故未重跑全量 pytest（交接文件记录 2026-08-26
  `.venv` 完整测试已验证通过）。
- 独立容器 `zhn-phase0-pg` 与卷 `zhn-phase0_data` 保留，供后续阶段复用空库。
  清理命令：`docker rm -f zhn-phase0-pg && docker volume rm zhn-phase0_data`
  （只作用于本阶段创建的独立资源，不影响现有项目）。

## git 状态

- 无源码改动；新增本报告 `docs/superpowers/reports/2026-08-26-stage0-migration-baseline.md`。
- 未提交、未 push（按交接文件工程约束，提交前先向用户确认）。
