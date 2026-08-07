# W7-4 受限公开演示部署说明

## 目标

把项目部署成可重复启动的受限演示环境，供面试官查看页面和分析链路。它不是生产部署，不承诺正式登录、高并发、备份或多租户隔离。

## 部署边界

- 页面只调用 FastAPI，不直接连接 PostgreSQL，也不把数据库密码放入前端。
- 公开演示使用分析员身份；管理员身份由服务器配置提供，不能从请求体或问题文本提升。
- `/analysis/{request_id}/approval` 只允许管理员调用，演示环境不公开管理员凭据。
- `/analysis/{request_id}/trace` 只允许请求本人或管理员查看；不把完整执行记录放进普通结果响应。
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
```

`MODEL_API_KEY` 只允许进入托管平台的服务器 Secret；不能进入前端响应、日志、镜像层、Compose 文件或 Git。`qwen-plus` 是部署示例，正式选择前仍需单独比较结构化输出稳定性、延迟、费用和数据出境边界。

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

公开链接上线前还必须补充 HTTPS、正式认证、限流、监控告警、备份恢复和冻结集验收；当前版本只作为受限演示。

## 本地验收记录

- 日期：2026-08-08
- 最新服务：http://127.0.0.1:8005
- `/health`：`200 {"status":"ok"}`
- `/ready`：`200 {"status":"ready"}`
- 全量回归：`399 passed in 2.26s`
- `docker compose --profile demo config --quiet`：通过。
- 本地 API 镜像构建：Dockerfile 已进入 CI；本机拉取 `python:3.12-slim` 时 Docker Hub IPv6 连接超时，不能记录为本地构建通过。
- 模型协议改造后，本地 Ollama 向后兼容验收通过：最新服务 `http://127.0.0.1:8007` 使用 UTF-8 请求完成“最近30天各渠道销售额是多少？”，状态 `succeeded`、重试 `0`，请求编号 `REQ-W7-UTF8-a5418099-3f6e-4207-96b2-4fec870f847c`。
- 远程 Qwen 真实端到端验收通过，服务为 `http://127.0.0.1:8008`：
  - “你是谁？”返回中文助手身份说明，轨迹为 `scope -> respond`，未生成或执行 SQL；请求编号 `REQ-W7-REMOTE-IDENTITY-216a4ec5`。
  - “删除订单数据”返回 `rejected/non_read_only`，轨迹为 `scope -> fail`，在访问数据库前拒绝；请求编号 `REQ-W7-REMOTE-WRITE-8ba8000f`。
  - “最近30天各渠道销售额是多少？”返回 `succeeded`、重试 `0`，结果为淘宝 `9000.00` 元、京东 `800.00` 元；轨迹覆盖远程领域门禁、Planner、SQL 生成、两层校验、PostgreSQL 执行和远程总结；请求编号 `REQ-W7-REMOTE-SALES-4e15b5e1`。
- 销售额请求中四个远程模型阶段均一次成功：领域门禁约 `2703 ms`、Planner 约 `2203 ms`、SQL 生成约 `2141 ms`、总结约 `2235 ms`。这些是单次本机验收记录，不代表 p50/p95 或费用结论。
- 请求与执行记录中未出现 API Key；密钥仅由服务器进程从 `.env` 读取并进入 Bearer 请求头，`.env` 不进入 Git。
