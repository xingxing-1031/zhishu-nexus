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

本地演示默认使用 Ollama `qwen3:4b`。公开部署前必须二选一：

1. 在同一私有网络提供兼容 Ollama API 的模型服务，并把 `OLLAMA_BASE_URL` 指向内网地址。
2. 增加经过审查的远程模型适配器和密钥管理，再进行独立的延迟、费用和数据出境评估。

不能把开发机的 `127.0.0.1:11434` 直接写进公网服务，也不能把 `.env`、数据库密码或模型密钥提交到仓库。

## 本地发布前验收

```powershell
docker compose up -d --wait
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m uvicorn retail_analytics_agent.app:app --host 0.0.0.0 --port 8004
```

另开终端检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8004/health
Invoke-WebRequest http://127.0.0.1:8004/ready
```

公开链接上线前还必须补充 HTTPS、正式认证、限流、监控告警、备份恢复和冻结集验收；当前版本只作为受限演示。
