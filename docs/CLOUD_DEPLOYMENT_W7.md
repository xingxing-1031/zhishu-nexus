# 云端 PostgreSQL 与 FastAPI 部署

这份文档对应 W7-4。目标是把本地已经验证的数据库结构和 FastAPI 镜像迁移到云端，形成一条可重复的发布流程。当前项目仍是受限演示版，不等同于生产系统。

如果使用自购 VPS 的单机部署，按 [VPS_DEPLOYMENT_W7.md](VPS_DEPLOYMENT_W7.md) 执行；本文件的托管数据库说明仍适用于拆分部署。

## 1. 云资源边界

需要两个资源：

1. 支持 `pgvector` 扩展的托管 PostgreSQL，并创建一个独立数据库和最小权限业务账号。
2. 能运行 Docker 镜像的 FastAPI Web Service，并提供公网 HTTPS 地址。

模型密钥只放在 Web Service 的服务器环境变量中。浏览器、镜像、Git 仓库和数据库迁移脚本都不保存模型密钥。

## 2. 配置变量

云端 API 服务至少需要配置：

```text
DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<database>?sslmode=require
MODEL_PROVIDER=openai_compatible
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-plus
MODEL_API_KEY=<server-side-secret>
MODEL_TIMEOUT_SECONDS=120
PUBLIC_DEMO_MODE=true
PUBLIC_DEMO_RATE_LIMIT_PER_MINUTE=6
PUBLIC_DEMO_MAX_ROWS=20
LOCAL_ACCESS_USER_ID=DEMO-USER
LOCAL_ACCESS_ROLE=analyst
```

`DATABASE_URL` 存在时会优先于 `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`。本地 Compose 继续使用拆分配置，避免把云数据库地址误传给本地 PostgreSQL 容器。

## 3. 初始化与迁移

云数据库必须先启用 `vector` 扩展。发布镜像已经包含 `db/` 目录，因此在 Web Service 的 release/pre-deploy command 中执行：

```bash
python -m retail_analytics_agent.migrate
```

该命令会按文件名顺序执行 `db/migrations/*.sql`，在 `schema_migrations` 中记录成功版本，默认导入演示种子数据并执行 `verify_delivery.sql`。单个版本失败时回滚该版本，不写入完成记录；再次执行时跳过已完成版本，不重复导入种子数据。

不需要演示数据的环境使用：

```bash
python -m retail_analytics_agent.migrate --skip-seed
```

生产数据变更应新增编号迁移文件，例如 `007_add_metric_version.sql`，不要修改已经执行过的旧文件，也不要依赖容器启动脚本重复建表。

## 4. Web Service 启动

构建目录为仓库根目录，启动命令为：

```bash
uvicorn retail_analytics_agent.app:app --host 0.0.0.0 --port ${PORT:-8000}
```

平台健康检查使用 `GET /health`（进程存活）和 `GET /ready`（数据库连接及业务关系就绪）。只有 `/ready` 返回 200 才允许平台把实例加入流量。

`PUBLIC_DEMO_MODE=true` 时，普通访问者只能使用分析接口，不能读取内部状态、审批和完整 Trace。

## 5. 发布验收

1. 在临时数据库或预发布数据库执行迁移命令。
2. 再执行一次迁移，确认输出为 `applied=0` 且没有重复种子数据。
3. 检查 `/health` 和 `/ready`。
4. 使用一个标准演示问题验证 SSE、表格、图表和降级路径。
5. 确认服务日志没有输出 `DATABASE_URL` 或 `MODEL_API_KEY`。

应用启动失败、迁移失败或 `/ready` 非 200 时，不应切换公网流量。迁移失败时恢复数据库备份或按新增的反向迁移方案处理，不能直接删除生产数据卷。

## 6. 当前边界

本版本已经具备 Docker 镜像、版本化迁移、幂等记录、业务就绪检查和公网演示所需的环境变量边界；还没有完成正式登录认证、网关级限流、密钥轮换、备份恢复演练、监控告警和 frozen holdout 验收。因此部署成功只能证明“可部署演示”，不能宣称生产就绪。
