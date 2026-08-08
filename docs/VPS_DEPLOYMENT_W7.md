# VPS 公网部署操作

这份文档用于已经购买 Linux 云服务器的受限演示部署。当前方案是一台 VPS 运行 Docker Compose、PostgreSQL/pgvector、FastAPI 和 Caddy；数据库只在 Compose 内网可见。

## 服务器准备

建议使用 Ubuntu 22.04、2 核 4 GB 内存、40 GB 以上 SSD。服务器安全组只开放 22（SSH）、80（证书申请）和 443（HTTPS）。不要开放 PostgreSQL 的 5432，也不要把 Ollama 的 11434 暴露到公网。本项目 VPS 版本调用远程模型 API。

## 部署步骤

在服务器安装 Docker 和 Compose 插件后执行：

```bash
git clone https://github.com/xingxing-1031/retail-analytics-agent.git
cd retail-analytics-agent
cp .env.vps.example .env.vps
nano .env.vps
```

把 `.env.vps` 中的数据库密码、模型密钥和域名替换为真实值。这个文件只保存在服务器，不提交 Git。

先启动数据库：

```bash
docker compose --env-file .env.vps -f compose.vps.yaml up -d postgres
```

执行一次迁移和业务验证：

```bash
docker compose --env-file .env.vps -f compose.vps.yaml --profile tools run --rm migrate
```

再次执行同一命令，应该看到 `applied=0 skipped=7`。然后启动 API 和 HTTPS 代理：

```bash
docker compose --env-file .env.vps -f compose.vps.yaml up -d api caddy
```

验证：

```bash
curl https://你的域名/health
curl https://你的域名/ready
```

## 更新代码

```bash
git pull --ff-only
docker compose --env-file .env.vps -f compose.vps.yaml --profile tools run --rm migrate
docker compose --env-file .env.vps -f compose.vps.yaml up -d --build api caddy
```

迁移失败时不要删除 `postgres_data` 数据卷。先查看迁移错误，修复后重新执行迁移；已成功的版本会被跳过。

## 演示边界

这是单 VPS 的公网演示，不是高可用生产部署。它还缺少正式登录认证、网关级限流、备份恢复演练、监控告警、密钥轮换和多实例部署。演示完成后应保存 `/health`、`/ready`、标准问题和迁移幂等的截图或日志作为验收证据。
