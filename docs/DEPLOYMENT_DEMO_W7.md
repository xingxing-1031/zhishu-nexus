# W7-4 受限公开演示部署说明

## 目标

把项目部署成可重复启动的受限演示环境，供面试官查看页面和分析链路。它不是生产部署，不承诺正式登录、高并发、备份或多租户隔离。

## 部署边界

- 页面只调用 FastAPI，不直接连接 PostgreSQL，也不把数据库密码放入前端。
- 公开演示强制使用分析员身份；`PUBLIC_DEMO_MODE=true` 与管理员角色不能同时启动。
- 公开模式关闭请求状态、人工审批和原始执行记录接口，避免共享演示身份让访客读取其他人的内部状态、SQL 或异常细节。
- 页面根据 `/session` 返回的服务器能力隐藏执行记录入口；后端仍独立拒绝对应接口，不能只依赖前端隐藏。
- 分析接口按来源地址执行单进程滑动窗口限流，并限制单次返回行数，控制远程模型和数据库资源消耗。
- 故障注入仅在测试替身和专项测试中启用，公开页面没有故障开关。
- PostgreSQL 使用只读业务查询链路；审计、审批和检查点仍使用独立的写入边界。

## 健康检查

| 接口 | 作用 | 适用场景 |
|---|---|---|
| `/health` | 进程存活 | 负载均衡器存活探针 |
| `/ready` | 数据库可连接且 `orders`、`order_items`、`products`、`refunds`、`knowledge_chunks` 已存在 | 发布后接收流量前的就绪探针 |

`/health` 返回 200 不代表可以执行分析；只有 `/ready` 返回 `{"status":"ready"}` 才表示业务数据结构已准备好。未就绪统一返回 503 和中文公共错误，不泄露连接异常。

## 当前模型前置条件

本地演示默认使用 Ollama `qwen3:4b`。公开部署选择 OpenAI 兼容协议的远程 Qwen，Planner、领域门禁、SQL 生成和总结继续复用原有 Pydantic 校验、重试、Trace 和安全工作流。

```text
MODEL_PROVIDER=openai_compatible
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-plus
MODEL_API_KEY=<server-secret>
MODEL_TIMEOUT_SECONDS=120
LOCAL_ACCESS_ROLE=analyst
PUBLIC_DEMO_MODE=true
PUBLIC_DEMO_RATE_LIMIT_PER_MINUTE=6
PUBLIC_DEMO_MAX_ROWS=20
```

`MODEL_API_KEY` 只允许进入托管平台的服务器 Secret；不能进入前端响应、日志、镜像层、Compose 文件或 Git。`qwen-plus` 是部署示例，正式选择前仍需单独比较结构化输出稳定性、延迟、费用和数据出境边界。

当前限流器保存在单个 API 进程内，适合单实例作品演示。多实例部署时每个进程拥有独立计数，且来源地址取决于平台代理配置，因此正式生产环境还需要可信代理、网关或 Redis 等共享限流设施。

不能把开发机的 `127.0.0.1:11434` 直接写进公网服务。2026-08-08 已使用服务器环境变量中的真实凭据完成远程 Qwen 端到端验收；这证明远程模型适配器可以进入既有安全工作流，但不等于公网部署或模型泛化评测已经完成。

## 本地发布前验收

```powershell
docker compose up -d --wait
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m uvicorn retail_analytics_agent.app:app --host 0.0.0.0 --port 8004
```

需要验证 API 容器时使用 `demo` profile。它会把 PostgreSQL 服务名注入为 `postgres`，默认以分析员身份运行，并把宿主机 Ollama 作为开发演示模型服务；公网环境不能照搬这个宿主机地址。

```powershell
docker compose --profile demo up -d --build --wait
```

另开终端检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8004/health
Invoke-WebRequest http://127.0.0.1:8004/ready
```

公开链接上线前还必须确认平台 HTTPS、Secret、数据库迁移和健康探针配置。正式认证、分布式限流、监控告警、备份恢复和冻结集验收仍属于后续生产边界。

## 本地验收记录

- 日期：2026-08-08
- 公开模式最新服务：http://127.0.0.1:8009
- 公开模式 `/health`：`200 {"status":"ok"}`
- 公开模式 `/ready`：`200 {"status":"ready"}`
- 保护层完成后的全量回归：`408 passed in 2.60s`
- `docker compose --profile demo config --quiet`：通过。
- 本地 API 镜像构建：Dockerfile 已进入 CI；本机拉取 `python:3.12-slim` 时 Docker Hub IPv6 连接超时，不能记录为本地构建通过。
- 模型协议改造后，本地 Ollama 向后兼容验收通过：最新服务 `http://127.0.0.1:8007` 使用 UTF-8 请求完成“最近30天各渠道销售额是多少？”，状态 `succeeded`、重试 `0`，请求编号 `REQ-W7-UTF8-a5418099-3f6e-4207-96b2-4fec870f847c`。
- 远程 Qwen 真实端到端验收通过，服务为 `http://127.0.0.1:8008`：
  - “你是谁？”返回中文助手身份说明，轨迹为 `scope -> respond`，未生成或执行 SQL；请求编号 `REQ-W7-REMOTE-IDENTITY-216a4ec5`。
  - “删除订单数据”返回 `rejected/non_read_only`，轨迹为 `scope -> fail`，在访问数据库前拒绝；请求编号 `REQ-W7-REMOTE-WRITE-8ba8000f`。
  - “最近30天各渠道销售额是多少？”返回 `succeeded`、重试 `0`，结果为淘宝 `9000.00` 元、京东 `800.00` 元；轨迹覆盖远程领域门禁、Planner、SQL 生成、两层校验、PostgreSQL 执行和远程总结；请求编号 `REQ-W7-REMOTE-SALES-4e15b5e1`。
- 销售额请求中四个远程模型阶段均一次成功：领域门禁约 `2703 ms`、Planner 约 `2203 ms`、SQL 生成约 `2141 ms`、总结约 `2235 ms`。这些是单次本机验收记录，不代表 p50/p95 或费用结论。
- 请求与执行记录中未出现 API Key；密钥仅由服务器进程从 `.env` 读取并进入 Bearer 请求头，`.env` 不进入 Git。
- 公开模式真实验收服务为 `http://127.0.0.1:8009`：`/session` 返回分析员、`public_demo_mode=true`、`trace_visible=false`；页面输入上限同步为 `20`，执行记录按钮不出现在可见 DOM 中。
- 公开模式 SSE 真实验收通过：身份问答返回助手答复；销售额查询仍返回淘宝 `9000.00` 元、京东 `800.00` 元；同一来源第三次请求返回 `429` 和 `Retry-After`；已知请求编号访问状态和 Trace 均返回 `403`。
- 最新保护层专项测试 `41 passed`；加入保护层后的全量回归为 `408 passed`。
- Dockerfile 已支持平台注入的 `PORT`，仍使用非 root `appuser`；这只证明镜像启动契约正确，不代表本机已经成功拉取并构建完整镜像。
