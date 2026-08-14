# 企析企业专业智能助理设计

## 产品定位

“企析”是一个完整的企业专业 Agent 工作系统。它负责意图识别、任务规划、上下文管理、工具调用、经营数据分析、多 Agent 协作、审核与流式交互。企业知识检索不是企析内部的简化模块，而是通过受认证的内部 Evidence API 调用独立的 `enterprise-knowledge-rag` 项目。

两个简历项目回答不同问题：

- 项目一“企析”证明完整 Agent 系统设计与工程实现能力。
- 项目二“企业知识库 RAG”证明文档治理、检索、排序、引用与评测的专项深度。

## 系统边界

```text
用户
  -> 企析 Supervisor
     -> General Agent -> Common MCP Tools
     -> Data Agent -> Text-to-SQL Runtime
     -> Knowledge Agent -> RAG Evidence API
     -> Collaboration -> Knowledge + Data + Synthesis + Review

企析 -> enterprise-knowledge-rag /internal/evidence
enterprise-knowledge-rag -X-> 企析内部 Agent
```

依赖方向必须保持单向。项目二只提供独立 RAG 对话能力和 Evidence API，不再负责企析的 Supervisor、通用工具、数据 Agent、综合 Agent或审核 Agent，也不反向调用项目一。

## 企析核心能力

### Supervisor 与计划

Supervisor 将请求分类为 `general`、`knowledge`、`data` 或 `collaboration`，输出有界的结构化计划。确定性的企业知识词和经营数据词优先形成安全边界，模型只处理真正含糊的请求。计划限制步骤数和允许调用的工具，避免无限循环和越权调用。

### 通用 Agent 与 MCP

通用 Agent 支持普通对话，并在需要实时或外部信息时调用白名单 MCP 工具。Common MCP Server 使用 Python MCP SDK、FastMCP 和 stdio，首批工具为：

- `time.now`
- `weather.current`
- `web.search`
- `web.fetch_summary`
- `exchange.rate`

工具经过发现、Schema 校验、超时、有限重试、响应大小限制和调用审计。外部工具失败时返回明确降级结果，不允许模型编造实时信息。未知远程 MCP、系统命令、文件协议、私网地址和任意数据库访问不在允许范围内。

### 企业知识 Agent

Knowledge Agent 只通过项目二的 `/internal/evidence` 获取企业知识证据。请求包含服务端身份、问题、对话上下文和证据预算；响应包含答案、引用、文档版本、检索观测和降级状态。项目一不复制项目二的切分、混合检索、Reranker、权限、版本、引用和拒答实现。

### 经营数据 Agent

Data Agent 复用项目一现有的经营分析 Runtime，包括业务 Skill、分析计划、目录检索、Text-to-SQL、SQLGlot AST 校验、业务一致性校验、只读执行、有限重试、人工审批、图表、数据证据和 MCP 报告导出。

### 多 Agent 协作

跨制度与经营数据的问题按需启动 Knowledge Agent、Data Agent、Synthesis Agent 和 Review Agent。综合 Agent 只能使用已验证的知识证据和数据证据；审核 Agent 检查引用、source ID、限制说明和任务完整性。普通请求不启动多 Agent。

### 上下文与状态

上下文保存最近对话、结构化任务计划、工具结果摘要、知识证据 ID、数据证据 ID 和失败状态。超过预算时压缩旧对话，但保留当前问题、关键约束和证据。LangGraph checkpoint 支持中断与恢复；有副作用的工具使用稳定幂等键，避免恢复后重复执行。

## 交互与可观测性

项目一成为“企析”的统一前端和公网演示入口。SSE 展示 Supervisor、工具调用、知识检索、数据分析、综合和审核阶段。界面展示当前 Agent、工具来源、文档引用、数据证据、图表、限制与降级状态。

每次任务记录路由、计划、Agent、工具名、参数哈希、耗时、状态和错误类型，不记录 API Key 或完整敏感响应。

## 项目二独立能力

项目二继续作为可单独部署和演示的企业知识库 RAG：

- 文档解析、清洗、切分和增量索引
- BM25、向量检索、RRF 和 Reranker
- Query Rewrite、补充检索和多跳证据
- 权限、版本和时间有效性
- 引用校验、证据不足拒答和检索观测
- Recall、MRR、NDCG、引用与拒答评测

项目二的简历和 README 不重复描述企析的通用工具、Text-to-SQL 或多 Agent 编排。

## 非目标

- 多租户 SaaS、计费和运营后台
- 任意企业数据库的自动适配
- 自动安装未知 MCP Server
- 模型训练、微调和分布式推理
- 复杂日历 OAuth 和写操作工具

## 验收标准

1. 项目一统一完成通用、知识、数据和协作请求的路由与回答。
2. 项目一可以通过 MCP 查询时间、天气、公开搜索、网页摘要和汇率，并正确降级。
3. 项目一只通过受认证 Evidence API 获取项目二的知识证据。
4. 项目二不依赖项目一，能够独立运行、评测和演示 RAG。
5. 两个项目分别拥有不重叠的 README、面试说明和可验证评测数据。
6. 后端、前端、SSE、部署与跨服务契约测试全部通过。

