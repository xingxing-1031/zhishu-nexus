# 系统架构

## 运行主链路

```mermaid
flowchart LR
    U["运营人员"] --> UI["v0.1 分析工作台"]
    UI -->|"POST /agent/stream 或 /analysis/stream"| API["FastAPI 边界"]
    API --> AUTH["可信 AccessContext"]
    AUTH --> AGENT["Agent Runtime"]
    AGENT --> GRAPH["LangGraph 工作流"]

    subgraph WORKFLOW["单 Agent 受控工作流"]
        PLAN["计划 AnalysisPlan"] --> RETRIEVE["检索 RetrievalEvidence"]
        RETRIEVE --> GEN["生成 SQL"]
        GEN --> AST["SQLGlot 只读校验"]
        AST --> BIZ["业务一致性校验"]
        BIZ --> RISK["演示级权限与风险判断"]
        RISK --> EXEC["安全执行"]
        EXEC --> SUMMARY["总结与 ChartSpec"]
    end

    GRAPH --> WORKFLOW
    AGENT --> SKILL["Skill Router / TaskPlan"]
    AGENT --> CONTEXT["Conversation Store / Context Builder"]
    AGENT --> REGISTRY["Tool Registry"]
    RETRIEVE --> CATALOG["版本化指标与 Schema 目录"]
    REGISTRY --> RAG["项目二内部 Evidence API"]
    RAG --> KNOWLEDGE["权限过滤 / Rerank / 引用边界"]
    REGISTRY --> MCP["MCP 报告导出工具"]
    PLAN --> OLLAMA["qwen3:4b / Ollama"]
    GEN --> OLLAMA
    SUMMARY --> OLLAMA
    EXEC --> PG["PostgreSQL 16 + pgvector"]
    RISK -->|"高风险"| HITL["人工审批 interrupt / resume"]
    HITL --> EXEC
    GRAPH <--> CHECKPOINT["PostgreSQL Checkpointer"]
    GRAPH --> TRACE["结构化 Execution Trace"]
    EXEC --> AUDIT["查询审计"]
    HITL --> AUDIT
    SUMMARY --> API
    API -->|"SSE 状态 / 结果 / 工具与证据"| UI

    subgraph ONBOARDING["管理员销售数据接入"]
        UPLOAD["注册 CSV / Parquet"] --> REG["dataset_registry"]
        REG --> STAGING["staging_<dataset>_<version>"]
        STAGING --> PROFILE["SchemaProfile + QualityReport + mapping draft"]
        PROFILE --> MAPPING["管理员提交映射"]
        MAPPING --> RECHECK["按当前 Schema 再校验"]
        RECHECK --> CONFIRMED["mapping_confirmed"]
        CONFIRMED --> READY["ready 数据集"]
    end
    API --> ONBOARDING
    READY -.-> PLAN
```

## 组件职责

| 边界 | 主要文件 | 职责 | 不负责 |
|---|---|---|---|
| HTTP 与演示 | `app.py`、`static/` | 可信身份注入、请求校验、SSE、审批和 Trace 展示 | 自己生成 SQL 或重新计算指标 |
| 工作流编排 | `workflow.py`、`analysis_service.py` | State、节点、条件边、重试、暂停和恢复 | 定义底层 SQLGlot 或 PostgreSQL 实现 |
| 模型适配 | `model_adapters.py`、`metric_domain.py` | 规划、SQL 生成、总结和域判断 | 决定最终安全权限 |
| 业务证据 | `knowledge.py`、`retrieval_adapters.py` | 指标公式、Schema、JOIN、版本和来源 | 执行 SQL |
| 双重校验 | `sql_safety.py`、`sql_consistency.py` | 检查只读语法和业务契约一致性 | 证明数据库权限绝对安全 |
| 查询执行 | `query_service.py`、`workflow_tools.py` | 只读事务、超时、强制 LIMIT、审计 | 判断用户身份 |
| 状态与审计 | `checkpointing.py`、`tracing.py`、`audit.py` | 快照恢复、系统 Trace、查询和审批记录 | 替代业务结果 |
| 评测 | `business_evaluation.py`、`evaluation_*` | 固定 Gold、分阶段评分和受控方案对比 | 修改 Agent 输出使其通过 |
| 数据接入 | `dataset_registry.py`、`data_import.py`、`schema_profiler.py` | 版本登记、隔离 staging、字段画像和质量门槛 | 自动猜测最终业务口径或绕过 SQL 安全 |

## 三类状态不要混淆

```text
AnalysisState
  单次工作流在节点之间传递的共享状态

PostgreSQL Checkpoint
  AnalysisState 在完整节点边界的持久化快照

Execution Trace / Audit
  Trace 解释系统如何运行；Audit 记录谁在何时做了什么
```

## 安全边界

模型提示词只负责降低错误概率，最终执行仍经过确定性边界：

```text
可信服务器身份
-> Pydantic 分析计划
-> 最小充分业务证据
-> SQLGlot AST 只读校验
-> 指标/JOIN/筛选业务一致性校验
-> 字段权限与高风险审批
-> 只读事务、超时、LIMIT
-> 独立审计与 Trace
```

当前为 v0.1 演示级权限体系：支持服务器配置的单账号认证与角色区分，并在 SQL AST 与确定性安全校验层限制允许访问的表、字段及敏感字段。关键词启发式判断仅用于前置拦截，不作为最终安全边界。正式多用户身份管理、多租户隔离和完整生产最小权限体系不在 v0.1 范围内。架构图描述 v0.1 已实现链路，不代表 K8s、云端高可用或生产安全认证已经完成。
