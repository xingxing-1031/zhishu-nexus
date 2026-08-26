# 阶段5：跨数据集真实评测基建交付 实施报告（2026-08-26）

> 交接来源：`docs/CLAUDE_UPGRADE_HANDOFF.md` 阶段5
> 仓库：`E:\qiuzhaoxiangmu\zhishu-nexus`（分支 main）

## 一、本阶段理解与计划

阶段5目标：用至少两套字段和分布不同的销售数据，证明迁移能力来自接入契约和语义映射，而
不是针对一张固定表写死。按 handoff 的六条要求逐项落点：

- **数据要求**：新增受控合成数据集 `cross_dataset_sales`（1000 行、2025 全年、列名/渠道值/
  区域/缺失模式均与固定 demo 表不同），保存来源说明、许可与快照 hash。
- **评测集**：新建跨数据集 `development`（28 例）与 `frozen v2`（13 例），不复用已消费的
  frozen holdout，覆盖 10 类场景。
- **评测器**：新增 `CrossDatasetCase`/`CrossDatasetObservation`/`CrossDatasetEvaluationReport`
  契约、确定性评分函数与报告聚合，支持 13 项指标中的确定性部分离线验证。
- **纪律**：不编造提升幅度；真实链路评测（需要模型/数据库）本次不运行，待批准后再执行；
  每条案例含输入、期望、gold 标签与理由。

按用户要求（"不需要本地测评，如果需要调用 API 先说"），本阶段交付构建性部分：数据、评测集、
评测器、单测；真实链路评分不在此次运行，报告如实说明边界。

## 二、实际修改文件

| 文件 | 改动 | 说明 |
|---|---|---|
| `scripts/build_cross_dataset_data.py` | **新增** | 确定性生成第二套销售 CSV，固定 seed `20260826`，输出 SHA-256 快照 |
| `evaluation/data/cross_dataset_sales.csv` | **新增** | 1000 行受控合成销售数据（生成产物） |
| `evaluation/data/cross_dataset_sales.csv.sha256` | **新增** | 快照摘要 |
| `evaluation/data/README.md` | **新增** | 数据来源/许可/快照 hash/与固定 demo 差异对照/已知边界 |
| `src/retail_analytics_agent/cross_dataset_evaluation.py` | **新增** | 跨数据集评测器：10 类枚举、5 种预期结局、案例契约、确定性评分、报告聚合、冻结守卫 |
| `evaluation/cross_dataset_development.jsonl` | **新增** | development 评测集（28 例，10 类全覆盖，用于调优） |
| `evaluation/cross_dataset_frozen_v2.jsonl` | **新增** | frozen v2 评测集（13 例，与 development 不重叠，一次性运行） |
| `tests/test_cross_dataset_evaluation.py` | **新增** | 20 个确定性单测（见下） |

`docs/CLAUDE_UPGRADE_HANDOFF.md` 为交接来源，按规则不提交。

## 三、为什么按这种方式实现

- **第二套数据刻意与固定表不同**：`order_id→order_no`、`sales_amount→gross_amount`、
  `quantity→qty`、`channel(app/web/store)→source(e_commerce/retail_store/catalog)`、
  `created_at→sale_date`、无区域→`region_code`，日期范围 2026→2025，且 region 3%、cost 9%
  缺失。8 个正确角色映射 + 4 个可自动生成指标（sales_amount/avg_order_value/order_count/
  units_sold）全部来自 `propose_mapping` 角色同义词与 `propose_metrics` 自动建议，证明迁移
  依赖契约而非写死列名。
- **评测器与既有链路分离**：`CrossDatasetExecutor` 是注入点，打分全部确定性可证；需要真实
  模型/数据库的部分（onboarding 状态机、SQL 执行、路由 LLM 层）由 executor 在批准后填充，
  契约侧可离线验证，不编造数字。
- **冻结纪律做成守卫函数**：`is_frozen_suite` 要求 frozen v2 每条案例带 `frozen_v2` tag 或属
  onboarding 类，防止 runner 对已冻结套件再调优；`aggregate_cross_dataset_report` 对无 case 的
  observation 直接抛错，避免脏数据混入。
- **gold 标签对齐系统确定性行为**：拒绝码取自 supervisor（`write_operation_refused`、
  `role_elevation_refused`、`dataset_not_found`、`empty_question`）与 scope（`dataset_unavailable`），
  澄清场景用 `ambiguous_request`（命中 `_AMBIGUOUS_TERMS` 的确定性规则），追问用
  `follow_up_context`；`expected_mode` 与路由返回一致（拒绝类写操作为 general、数据请求为 data）。
- **gold_rows 只填确定性行数**：渠道 3 行、区域 4 行、品类 3 行、聚合单行等，来自数据分布定义
  （最小权重 10% 在 1000 行中必出现），不虚构具体数值结果。

## 四、新增/修改的测试

新增 `tests/test_cross_dataset_evaluation.py` 20 个，全部离线运行：

- 套件加载：development 覆盖 10 类、frozen 不重叠、`is_frozen_suite` 守卫（frozen 为真、dev 为假）。
- 契约校验：succeeded 必须有 mode、refused/clarification 必须有 reason_code、gold_rows 仅限 succeeded。
- 确定性评分：onboarding 完成率、mapping 匹配计数、metric 可用率、SQL 安全（blocked==不安全）、
  越权泄漏计数。
- 单案例打分：正确运行全 flag 通过、错误结局使 route 失败、安全查询被 block 使 sql_safety 失败、
  澄清标记匹配、越权拒绝放行 permission。
- 报告聚合：全对套件 13 项指标、executed 计数（error_type 计入 total 不计入 executed）、
  observation 无对应 case 抛错、`model_dump(mode="json")` 可序列化。

## 五、完整测试命令和真实输出

```powershell
cd E:\qiuzhaoxiangmu\zhishu-nexus
.\.venv\Scripts\python.exe -m pytest tests\test_cross_dataset_evaluation.py -q
# 20 passed

.\.venv\Scripts\python.exe -m pytest
# 679 passed（阶段4为 659，新增 20），无 failed/error/skipped
```

评测集加载校验（离线）：

```
development cases: 28
frozen v2 cases: 13
dev categories: 10 类全覆盖
frozen categories: 10 类全覆盖
overlap ids: 空
is_frozen_suite(frozen): True
is_frozen_suite(dev): False
validation issues: 0
```

## 六、已知边界和未完成项

- **真实链路评测未运行**：本阶段只交付构建性部分。onboarding/mapping/metric/SQL/路由/回答等
  真实环节需要模型与数据库（zhn-phase0-pg 端口未暴露、ollama/dashscope API），按用户要求本次
  不调用。批准后由 `CrossDatasetExecutor` 执行，13 项指标中依赖真实链路的
  `onboarding_success_rate`、`mapping_field_accuracy`、`metric_availability_accuracy`、
  `sql_execution_success`、`business_result_accuracy`、`p50/p95_latency` 待真实采集后填写，
  不编造提升幅度。token/cost 指标只有真实采集时才报告（handoff 纪律）。
- **`sales_region` 类列名边界**：现有 `propose_mapping` 的 `amount` 角色同义词含 `sales`，
  会把 `sales_region` 误判为金额列。本数据集用 `region_code` 规避；该边界在 README 与报告中
  记录，未修改核心映射逻辑（避免破坏既有测试）。
- **follow_up 案例依赖上一轮上下文**：`cs-dev-follow-001/002` 与 `cs-f2-follow-001` 的期望
  按 `previous_mode=data` 标注，真实评测执行时须携带上下文。
- **reason_code 部分为描述性标注**：如 `metric_unavailable`、`unsafe_sql_blocked`、
  `quality_warning`，这些不参与打分（打分只基于 outcome/mode/sql_blocked/evidence），仅作为
  记录与人工核对依据。
- **空结果案例**：`cs-dev-empty-001` 期望返回空结果并说明原因，属正常成功链路，不包含数据证据。

## 七、git diff --stat 与 git status --short

```
 scripts/build_cross_dataset_data.py                    |  103 +++
 src/retail_analytics_agent/cross_dataset_evaluation.py |  367 ++++
 tests/test_cross_dataset_evaluation.py                 |  292 ++++
 evaluation/cross_dataset_development.jsonl             |   28 行
 evaluation/cross_dataset_frozen_v2.jsonl               |   13 行
 evaluation/data/cross_dataset_sales.csv                | 1001 行
 evaluation/data/cross_dataset_sales.csv.sha256         |    1 行
 evaluation/data/README.md                              |   55 行
```

`git status --short`：

```
?? docs/CLAUDE_UPGRADE_HANDOFF.md
?? evaluation/cross_dataset_development.jsonl
?? evaluation/cross_dataset_frozen_v2.jsonl
?? evaluation/data/
?? scripts/build_cross_dataset_data.py
?? src/retail_analytics_agent/cross_dataset_evaluation.py
?? tests/test_cross_dataset_evaluation.py
```
