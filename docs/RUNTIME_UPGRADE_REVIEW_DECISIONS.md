# Runtime 升级审查决策记录

> 2026-08-27 · 由代码审查（ZCode）产出，记录本轮验收结论、已执行的安全子集与明确延期的项。
> 状态标签含义：**已实现**＝代码进入主干；**单测验证**＝行为由自动化测试锁定；
> **未生产验证**＝尚未在真实部署流量中运行过。

## 一、审查总结论

Runtime 升级方案 8 个阶段中 6 个完整兑现（Harness / Context / Contract / Trace 归因 /
故障注入 / 门禁框架），Checkpoint 分层与统一授权为机制完成但原实现未接入生产路径。
本次审查后按最小安全子集完成了接线与收窄；全部改动由全量测试回归保护。

## 二、本次已执行的决策

### D1 CheckpointMeta 守卫接线（状态：已实现 + 单测验证）

- `analysis_service.get_analysis_runner` 与 `evaluation_runtime` 两处构造点显式传入
  `checkpoint_meta` store；生产使用模块级共享实例，评测用例之间使用独立实例保证隔离。
- 生效的守卫规则：恢复请求归属校验、state_version 兼容校验、过期校验。
- **边界如实声明**：共享实例随进程重启清空，不跨实例同步；LangGraph 主 Checkpoint
  本身在 PostgreSQL 中持久，meta 是进程内的附加守卫层。两者不要混为一谈。

### D2 authorize() 默认方向改为 fail-closed（状态：已实现 + 单测验证）

- 未接线的动作 `rag.retrieve` / `evidence.return` 显式返回拒绝
  （reason=authorization rule not configured for this action），
  而不是落进通用放行分支。
- 无法匹配任何规则的资源组合返回拒绝
  （reason=no authorization rule matched this resource）。
- `AuthorizationDecision` 新增 `purpose` 字段并保留入参值，审计可追溯调用意图。
- 兼容性说明：`dataset:*` 资源在 policy 为 None 或空白名单时仍然放行，
  这是当前角色双轨制（analyst/admin、无细粒度存储）下有意保留的过渡语义，
  见下方延期项 D5。

### D3 评测集与协议文档对齐（状态：已实现）

- development 扩至 21 例（新增 2 例权限收窄用例）；frozen 12 例保持不动。
- EVALUATION_PROTOCOL.md 增补八层 harness 套件小节：契约级证明的定位、
  frozen 变更纪律、RUNTIME_EVAL_WRITE_REPORTS 留存开关。

## 三、明确延期（含理由）

| 编号 | 事项 | 理由 |
|---|---|---|
| D4 | RAG_RETRIEVE / EVIDENCE_RETURN 的实际接线 | 规则来源需要先回答"知识库文档权限数据放在哪"，属产品决策；在配置出现前保持拒绝是安全默认 |
| D5 | 每用户数据集 ACL 存储模型 | 需要 schema 与管理界面支持；过渡期依赖 dataset_resolver 审计 + 角色 角色 维度控制，风险可控 |
| D6 | PermissionAuditLog 持久化 | 当前为进程内存列表，长驻进程存在无界增长风险；在持久化方案落地前不接入生产热路径，仅测试使用 |
| D7 | DB-backed CheckpointMetaStore | 依赖迁移脚本编排；现进程内实现已覆盖恢复期三类核心校验 |
| D8 | 远程模型端到端 harness 指标 | 需要真实模型预算批准；现有八层结果均为离线确定性探针 |

## 四、面试表述口径（摘要，详见 mianshizhunbei/13-实战复盘）

> 统一授权我做了两层处理：已接线的动作在运行时逐次校验，没接线的动作默认拒绝而不是默认放行；
> Checkpoint 恢复前会重新校验归属、版本和过期。这是我审查 AI 提交时发现"机制写完但没接线"
> 问题后做的收口——宁可暴露真实边界，也不让安全层停留在纸面。
