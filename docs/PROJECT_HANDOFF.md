# 项目交接文档

> 用途：供新的 Codex 对话或开发者在不依赖历史聊天记录的情况下接管项目。
>
> 最后核对时间：2026-08-15（Asia/Shanghai）

## 1. 接管入口

开始任何修改前，依次读取：

1. `AGENTS.md`
2. 本文档 `docs/PROJECT_HANDOFF.md`
3. `README.md`
4. `docs/ARCHITECTURE.md`
5. `docs/FINAL_ACCEPTANCE.md`
6. `docs/OPERATIONS_W8.md`
7. `git status -sb`
8. `git log -10 --oneline`

如本文档与聊天摘要冲突，以当前代码、Git 提交和可复现验证结果为准。不要根据旧聊天记录覆盖较新的代码事实。

## 2. 当前快照

| 项目 | 当前值 |
|---|---|
| 仓库目录 | `E:\qiuzhaoxiangmu\zhishu-nexus` |
| GitHub | `xingxing-1031/zhishu-nexus`（私有仓库） |
| 默认分支 | `main` |
| 当前提交 | 运行 `git log -1 --oneline` 获取，本文不固化自引用提交 |
| 工作区 | 当前交接文档已纳入版本控制；除用户本地未跟踪文件外，工作区干净 |
| 公网演示 | `http://106.52.176.63/` |
| 域名 | `yuxingji.cn`，DNS 已指向 VPS，但因 ICP 备案未完成被腾讯云拦截 |
| HTTPS | 尚未启用；备案完成后再让 Caddy 申请证书 |
| 公网身份 | `PUBLIC_DEMO_MODE=true`，固定分析员身份 |
| 公网模型 | OpenAI 兼容协议的远程 Qwen，凭据只在服务器环境变量中 |
| 本地模型 | Ollama `qwen3:4b` |
| 数据库 | PostgreSQL 16 + pgvector |
| 前端 | React 18 + TypeScript + Vite + ECharts + Lucide |
| 后端 | FastAPI + LangGraph + Pydantic + SQLGlot + psycopg |

当前提交的自动化结果：

- GitHub Actions `CI`：成功，运行编号 `31832696721`。
- GitHub Actions `Deploy VPS release`：成功，运行编号 `31832696736`。
- 生产发布脚本最终输出并通过 `/ready` 检查。
- 公网页面已实际执行“统计最近30天各销售渠道的销售额”，返回中文结论、4 行真实数据、图表、计划和审计依据。
- 390px 移动视口检查未出现横向溢出。
- 对话历史已改为服务器快照优先，删除记录不会在其他设备上复活；页面每 5 秒轮询账号会话列表，手机端删除按钮始终可见。
- 对话同步修复提交：`02cf014`、`9fa7998`。

## 3. 项目定位

项目名称：**知枢 Nexus 企业智能 Agent 平台**。

知枢 Nexus 连接企业知识、经营数据与受控工具。可审计零售经营分析是 Data Agent 的特化能力，不再作为整个平台名称。

目标用户是不熟悉 SQL 的零售运营人员。用户通过自然语言查询订单、商品、渠道和退款数据，系统必须做到：

- 结果来自真实 PostgreSQL 查询，不由模型编造数值。
- 指标公式、固定筛选、来源表和 JOIN 有版本化业务依据。
- 模型输出进入数据库前经过确定性安全与业务校验。
- 高风险查询需要可信管理员审批。
- 计划、证据、SQL、执行状态、结果和审计记录可以追溯。
- 模型总结失败时保留可信表格并明确降级，不编造结论。

这是面向秋招和实习投递的高质量项目，当前定位是“受限公开演示 + 轻量生产运维基线”，不是多租户、高可用的正式生产平台。

## 4. 已实现主链路

```text
自然语言问题
-> 范围和意图判断
-> 结构化 AnalysisPlan
-> 版本化指标与 Schema 证据检索
-> RetrievalEvidence
-> SQL 生成
-> SQLGlot AST 只读校验
-> 业务一致性校验
-> 权限和风险判断
-> 必要时人工审批 interrupt / resume
-> PostgreSQL 只读执行
-> ChartSpec 与中文结论
-> SSE 返回进度、表格、图表和审计依据
```

关键认识：

- `AnalysisPlan` 描述用户想分析什么，是检索输入。
- `RetrievalEvidence` 是检索后选出的指标、表、字段、固定规则和 JOIN，是 SQL 生成的最小充分证据。
- SQLGlot 负责解析 AST 和只读安全，不证明 SQL 符合业务口径。
- 业务一致性校验独立检查公式、表、JOIN、固定筛选和维度分组。
- Executor 只执行查询，不给自己的结果打分。

## 5. 关键组件职责

| 组件 | 主要文件 | 职责 |
|---|---|---|
| HTTP 与会话边界 | `app.py` | FastAPI、可信身份、限流、SSE、公开模式和管理接口 |
| LangGraph 编排 | `workflow.py`、`analysis_service.py` | 状态、节点、条件边、有限重试、审批暂停和恢复 |
| 模型适配 | `model_adapters.py`、`metric_domain.py` | Planner、领域判断、SQL 生成、总结 |
| 指标和 Schema | `knowledge.py`、`retrieval_adapters.py` | 指标版本、公式、来源、JOIN 和检索证据 |
| SQL 安全 | `sql_safety.py` | AST 解析、只读限制、表字段边界、LIMIT 等 |
| 业务校验 | `sql_consistency.py` | 公式、固定筛选、Evidence、JOIN 和维度一致性 |
| 查询执行 | `query_service.py`、`workflow_tools.py` | 只读事务、超时、连接池、结果行数和审计 |
| 状态与追踪 | `checkpointing.py`、`tracing.py`、`audit.py` | Checkpoint、Execution Trace、查询与审批审计 |
| 独立评测 | `business_evaluation.py`、`evaluation_*` | Gold、分阶段评分、方案对比和报告保存 |
| 前端 | `frontend/src/` | 中文交互、SSE 进度、图表、表格、证据和管理页 |

三类记录不能混淆：

- `AnalysisState`：单次工作流节点间共享状态。
- PostgreSQL Checkpoint：完整节点边界的可恢复快照。
- Execution Trace / Audit：Trace 解释系统如何运行；Audit 记录谁在何时做了什么。

## 6. 数据模型与业务语义

核心业务表：

- `orders`：订单、渠道、状态、时间等订单级信息。
- `order_items`：订单明细、商品、数量和历史成交价快照。
- `products`：商品名称、品类和当前商品信息。
- `refunds`：退款金额、状态、原因和关联订单。

必须理解的关系：

- 一张订单可以有多条订单明细。
- 销售金额必须使用 `order_items.quantity * order_items.unit_price`，不能只数订单行。
- 订单级退款与商品明细强行 JOIN 可能产生一对多重复计算。
- 销售额默认只统计业务定义允许的已支付订单。
- 时间按 `Asia/Shanghai` 业务时区解释，不能随意按 UTC 日期切分。

当前版本化指标包括：

- 销售额
- 订单数
- 销售件数
- 退款金额
- 退款笔数
- 平均订单金额

指标定义保存公式、来源字段、固定规则、支持维度、版本和稳定 `source_id`。生产工作流目前使用确定性的最小证据检索；关键词、向量、RRF 与可选 Reranker 只用于受控评测对比，未接入线上主链路。

## 7. API 契约

以下现有接口和数据字段属于前后端契约，修改前必须检查所有调用方和测试：

```text
GET  /health
GET  /ready
GET  /session
GET  /demo/overview
POST /auth/login
POST /auth/logout
POST /analysis/run
POST /analysis/stream
GET  /analysis/{request_id}
GET  /analysis/{request_id}/trace
POST /analysis/{request_id}/approval
GET  /admin/audit
GET  /admin/metrics
```

关键结构：

- `SessionInfo`：`user_id`、`role`、`public_demo_mode`、`trace_visible`、`max_rows`
- `AnalysisRequest`：`request_id`、`user_id`、`question`、`max_rows`
- `AnalysisPlan`：`analysis_goal`、`metrics`、`dimensions`、`filters`、`time_range`、`sort`、`limit`
- `AnalysisResult`：`status`、`access_role`、`answer`、`plan`、`rows`、`chart_spec`、`evidence_source_ids`、`retry_count`、`degradation_reason`、`trace`
- `ApprovalRequired`：`request_id`、`sql`、`sql_fingerprint`、`reasons`、`sensitive_columns`、`result_limit`、`trace`
- `TraceEvent`：`component`、`status`、`attempt`、`occurred_at`、`duration_ms`、`error_type`、`error_message`、`retry_delay_ms`

前端不得直接连接 PostgreSQL，也不得自行生成或执行 SQL。

## 8. 前端现状

前端位于 `frontend/`，生产构建由 Dockerfile 的 Node 构建阶段完成，再复制到 Python 包的 `static/` 目录。

当前视觉系统来自 Stitch 设计方向：

- 深色左侧导航 `#121B2E`
- 主色 `#0F766E`
- 辅助蓝 `#2563EB`
- 页面背景约 `#F5F7FA`
- 文字 `#172033`，次文字 `#667085`
- 4px 基础间距，4px 控件圆角，8px 容器圆角
- 中文回退字体为 Noto Sans SC；SQL、请求编号和数值使用等宽字体

当前页面：

- 分析工作台
- 管理员审计记录
- 管理员指标口径
- 受控登录页
- 审批抽屉
- 执行记录抽屉

中文边界：

- 普通用户可见的标题、状态、错误、拒绝原因、模型回答和图表标题使用中文。
- SQL、请求编号、数据库表名、`source_id`、Schema 关系和必要的管理员技术标识保留英文。
- 后端英文错误不会直接透传给普通用户，前端通过 `localizeUserMessage` 转换为稳定中文提示。

2026-08-10 已移除没有行为的移动菜单和帮助按钮，避免出现“能点但无响应”的 Demo 感。

## 9. 权限与安全边界

确定性安全链路：

```text
可信服务器身份
-> Pydantic 计划校验
-> 最小充分 RetrievalEvidence
-> SQLGlot AST 只读校验
-> 业务一致性校验
-> 表/字段与角色权限
-> 高风险人工审批
-> 只读事务、超时和 LIMIT
-> 独立审计与 Trace
```

重要边界：

- 角色来自服务器认证或演示配置，不接受客户端自行声明管理员。
- Prompt 只降低模型犯错概率，不能替代代码校验。
- 普通分析员无权读取敏感退款原因。
- 管理员也不能执行删除、更新或插入等写操作。
- 审批绑定 SQL 指纹；审批后 SQL 发生变化必须重新审批。
- `rejected` 表示执行前主动拒绝；`failed` 表示允许开始后发生技术失败；`degraded` 表示核心可信结果存在但非核心表达层失败。

公开演示模式：

- 强制分析员角色。
- 关闭请求详情、审批和原始 Trace 接口。
- 单进程按来源地址限流，默认每分钟 6 次。
- 最大返回 20 行。
- 适合作品演示，不是分布式限流或多租户认证。

## 10. 容错、幂等和降级

已实现：

- 瞬时模型错误有限重试。
- 指数退避、随机抖动和总时间预算。
- 确定性错误不重试。
- API 请求指纹和 `request_id` 幂等；同 ID 不同输入返回冲突。
- 审批、审计和请求登记具有独立幂等边界。
- 模型总结失败时保留已验证 rows 和图表数据，返回降级说明。
- 数据库执行失败不能伪装成降级成功。
- 故障注入只存在于测试替身，不暴露到公网 UI。

## 11. 评测事实与禁止宣传

Development 对比：

- 40 条 development。
- baseline、混合检索、混合检索 + Reranker 三种方案。
- 严格控制 Planner、SQL 生成、执行器、数据库快照和评测器等变量。
- 共运行 120 次真实工作流。
- 修复共享 Planner、时间语义和评测器问题后，三个方案六个核心阶段在 development 上均为 100%。
- 这不能表述为“Agent 准确率 100%”。

Frozen holdout 最终验收：

- 20 条独立冻结题，只运行一次。
- 核心通过率 `35.00%`。
- 平均延迟 `5689.90 ms`。
- Plan `45.45%`、Evidence `81.82%`、SQL `66.67%`、Outcome `60.00%`、Rows `47.37%`、Chart `90.91%`。
- `answer_pass_rate=null`，因为没有独立自然语言答案评审器。
- 原始报告：`evaluation/reports/final_holdout.json`。
- 该 holdout 已被正式消费，不能针对失败题优化后继续把它称为独立冻结验收。

简历可以强调：

- 建立了固定数据库快照、可信 Gold、分阶段评分、检索方案对比和无测试泄漏的评测体系。
- 评测发现泛化问题并明确系统边界。

简历不能写：

- “Agent 准确率 100%”
- “生产级系统”
- “支持任意数据库或任意行业”
- 没有原始报告支持的提升比例

## 12. 部署与访问

VPS：

- 公网 IP：`106.52.176.63`
- 项目目录：`/home/ubuntu/retail-analytics-agent`（为避免发布中断保留的 VPS 兼容路径，不代表当前产品名）
- 当前访问：`http://106.52.176.63/`
- Caddy 当前使用 `SITE_ADDRESS=:80`
- PostgreSQL、API 和 Caddy 由 `compose.vps.yaml` 编排

域名：

- `yuxingji.cn` 和相关 DNS 已指向 VPS。
- 腾讯云当前返回“网站未完成备案”，因此域名被拦截。
- 备案完成前继续使用 IP + HTTP 演示。
- 备案完成后把服务器 `.env.vps` 的 `SITE_ADDRESS` 改为 `yuxingji.cn`，重建 Caddy 后由 Caddy 自动申请和续期 HTTPS 证书。

自动发布：

- 推送 `main` 会自动触发 `.github/workflows/deploy-vps.yml`。
- 工作流也支持手动指定 Git 提交、分支或标签。
- 工作流把当前仓库中的最新版发布脚本复制到 VPS 临时目录，避免服务器旧脚本阻止自身升级。
- 发布脚本拒绝覆盖服务器上的未知本地修改，只忽略自身生成的 `.deployed-release` 标记。
- 发布过程执行迁移、构建 API/Caddy、启动容器并检查 `/ready`。

**高风险提醒：推送 `main` 会直接部署公网。开发新功能时先使用分支并完成验证，不要把未验证改动直接推送到 `main`。**

回滚：

- 手动运行发布工作流并指定上一个已验证提交。
- 应用代码可以回滚；数据库迁移不会自动回滚，迁移必须保持向前兼容。

## 13. 备份和运维

现有脚本：

- `ops/vps_backup.sh`：PostgreSQL 自定义格式备份，默认保留 14 天。
- `ops/vps_restore_drill.sh`：恢复到临时数据库并校验，不修改在线业务库。
- `ops/vps_healthcheck.sh`：检查 `/ready` 和磁盘，写 JSONL 日志，可接 Webhook。
- `ops/vps_release.sh`：安全发布和就绪检查。

当前边界：

- 备份仍主要保存在单台 VPS，本机损坏无法覆盖整机丢失。
- 尚未接入腾讯云 COS 等独立对象存储。
- 尚未完成外部监控告警、集中日志、压测和正式灾备验收。

## 14. 本地开发和验证

推荐重新创建本地虚拟环境：

```powershell
cd E:\qiuzhaoxiangmu\zhishu-nexus
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
```

数据库：

```powershell
docker compose up -d --wait
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U retail_user -d retail_analytics -f /opt/retail-db/verification/verify_delivery.sql
```

前端：

```powershell
cd frontend
npm ci
npm run build
```

已知本机情况：

- 旧 `.venv` 曾引用不存在的 Python 3.12 路径，导致本机无法启动 pytest；需要重建虚拟环境。
- 旧编辑器/WorkBuddy 进程曾占用 `tsconfig.app.tsbuildinfo` 和静态资源目录，导致本地增量构建出现 `EPERM`。
- 通过无增量 TypeScript 检查和隔离输出目录完成过生产构建验证。
- 当前提交在干净 GitHub Actions 环境中的 CI 和 Docker/VPS 构建已经成功，因此上述本机锁文件不是代码构建失败。
- ECharts 懒加载 chunk 约 520 KB，构建有 chunk size warning；当前不阻塞演示，后续只有在真实首屏性能数据表明必要时再拆分。

## 15. 已知不一致和待核对问题

以下问题应由新对话先确认，不要静默忽略：

1. `README.md` 仍写着 W7-4 公开演示准备中，实际新版公网已经部署，应更新当前状态。
2. `pyproject.toml` 的 dev 依赖仍包含 `httpx2>=2,<3`。这看起来是误写或幽灵依赖，应确认后删除，并在干净环境重新运行测试。
3. README 中旧测试数量和文档中的 `408 passed` 是历史验收记录；新的简历数字必须以当前 CI 或重新执行的测试结果为准。
4. Frozen holdout 已经消费且核心通过率只有 35%，不能通过针对具体失败题调参后继续称其为未见测试。
5. 公网演示仍是共享分析员身份，不是正式账号系统。
6. 域名 HTTPS 受备案阻塞，不是 Caddy 或 DNS 代码故障。

## 16. 推荐下一步顺序

### P0：投递前收尾

1. 修正 README 当前状态和已过期数字。
2. 核对并删除 `httpx2`，重建 `.venv`，运行完整 pytest 和 Ruff。
3. 检查 GitHub README、简历描述、演示数据和真实报告数字一致。
4. 录制 2 至 3 分钟演示视频，准备典型成功、拒绝和边界场景。
5. 立即用项目一开始投递实习，不等待项目二完成。

### P1：访问与轻量运维

1. 等待 ICP 备案完成。
2. 切换 `SITE_ADDRESS=yuxingji.cn` 并验证 HTTPS。
3. 实际执行一次备份和无损恢复演练。
4. 决定是否保持无登录公开演示；面试链接通常优先低摩擦访问，不必强迫访客注册。

### P2：后续优化或项目二

1. 根据新的 development 证据优化 Planner、SQL 生成和工作流策略。
2. 如需再次宣称泛化结果，建立全新的未见 holdout，不复用已消费题集。
3. 不为追求“生产级”无限扩张当前项目；下一主项目应转向电商订单库存后端，展示事务、并发、缓存、幂等、状态机和异步消息能力。

## 17. 不要做的事情

- 不要使用 `git reset --hard` 或强制覆盖用户改动。
- 不要执行 `docker compose down -v` 删除本地或服务器数据卷。
- 不要把 `.env`、`.env.vps`、模型 API Key、数据库密码、SSH 私钥写入 Git、日志或前端。
- 不要在公开页面暴露管理员账号、完整 SQL、原始 Trace、故障注入或敏感退款原因。
- 不要让前端绕过 FastAPI 直接访问数据库。
- 不要把 Prompt 当作最终安全边界。
- 不要在没有独立评测证据时修改简历指标。
- 不要因为推送方便就把未验证代码直接提交到 `main`；它会自动部署公网。

## 18. 新对话首条消息模板

```text
请接手知枢 Nexus 企业智能 Agent 平台项目。

项目目录：
E:\qiuzhaoxiangmu\zhishu-nexus

开始工作前，请完整读取：
- AGENTS.md
- README.md
- docs/PROJECT_HANDOFF.md
- docs/ARCHITECTURE.md
- docs/FINAL_ACCEPTANCE.md
- docs/OPERATIONS_W8.md
- 最近 10 条 Git 提交
- 当前 Git 工作区状态

当前公网演示：
http://106.52.176.63/

当前 main 推送会自动部署公网。请先总结当前状态、已完成能力、验证证据、风险边界和待办事项，不要立即修改代码。确认理解后，再从 PROJECT_HANDOFF.md 的 P0 投递前收尾开始。
```

## 19. 接管完成标准

新的对话只有在能够准确回答以下问题后，才算完成接管：

1. `AnalysisPlan` 和 `RetrievalEvidence` 的职责有什么区别？
2. SQLGlot 安全校验和业务一致性校验为什么不能互相替代？
3. 为什么公开模式不能开放完整 Trace 和审批接口？
4. 为什么 development 100% 不能写成 Agent 准确率 100%？
5. 当前 frozen holdout 的真实结果和使用边界是什么？
6. 当前公网为什么使用 IP 而不是域名 HTTPS？
7. 为什么推送 `main` 前必须先完成验证？
8. Checkpointer、Audit 和 Execution Trace 分别解决什么问题？

回答清楚以上问题后，再进入新的实现任务。
