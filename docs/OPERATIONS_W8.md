# VPS 轻量生产运维基线

本项目的目标是单台 VPS 上可控、可恢复、可审计的演示和实习项目部署，不是高可用生产集群。所有命令在 `/home/ubuntu/retail-analytics-agent` 执行。

## 备份与恢复演练

每天执行一次 PostgreSQL 自定义格式备份：

```bash
./ops/vps_backup.sh
```

备份保存在服务器本机的 `backups/postgres`，默认保留 14 天，并生成 SHA-256 校验文件。它可以防止误删或数据卷损坏，但不能抵御整台 VPS 丢失。正式灾备还需要把备份复制到腾讯云 COS 或其他独立对象存储。

使用备份做无损恢复演练：

```bash
./ops/vps_restore_drill.sh /home/ubuntu/retail-analytics-agent/backups/postgres/retail_YYYYMMDDTHHMMSSZ.dump
```

演练会恢复到临时数据库、检查订单表，然后删除临时数据库，不修改正在服务的业务库。

## 健康检查与告警

```bash
./ops/vps_healthcheck.sh
```

脚本检查 `/ready` 和磁盘占用，并把 JSONL 结果写入 `logs/healthcheck.jsonl`。配置 `ALERT_WEBHOOK_URL` 后，失败时可以通知企业微信、钉钉或其他 Webhook 服务；未配置时仍会保留日志并返回非零退出码。

建议使用 `crontab`：

```cron
15 2 * * * cd /home/ubuntu/retail-analytics-agent && ./ops/vps_backup.sh >> logs/backup-cron.log 2>&1
*/5 * * * * cd /home/ubuntu/retail-analytics-agent && ./ops/vps_healthcheck.sh >> logs/healthcheck-cron.log 2>&1
```

## 发布与回滚

发布指定 Git 提交、分支或标签：

```bash
./ops/vps_release.sh <git-ref>
```

脚本会拒绝服务器工作区存在未提交修改的情况，执行迁移、重建 API 和 Caddy，并验证 `/ready`。回滚时传入上一个已验证的 Git 提交。脚本只回滚应用代码，不自动回滚已经执行的数据库迁移；迁移必须保持向前兼容。

GitHub Actions 的手动发布工作流需要配置以下 Repository Secrets：

```text
VPS_HOST
VPS_USER
VPS_SSH_PRIVATE_KEY
VPS_KNOWN_HOSTS
```

## 登录与 HTTPS

当前 VPS 可以保持 `AUTH_MODE=demo` 和 `PUBLIC_DEMO_MODE=true` 作为公开演示。正式启用单租户登录时，设置：

```text
AUTH_MODE=password
PUBLIC_DEMO_MODE=false
AUTH_USERNAME=...
AUTH_USER_ID=...
AUTH_ROLE=analyst
AUTH_PASSWORD_HASH=...
AUTH_SESSION_SECRET=至少 32 个字符
AUTH_COOKIE_SECURE=true
```

域名需要由用户购买、实名认证并完成中国大陆服务器所需的 ICP 备案，再将 DNS 解析到 VPS。把 `SITE_ADDRESS` 改成域名后，Caddy 会自动申请和续期 HTTPS 证书。

## 当前边界

- 连接池、结构化 HTTP 日志、健康检查、备份脚本和恢复演练已纳入代码。
- 当前是单台 VPS、单租户配置账号，不是多租户身份平台。
- 冻结集验收必须使用独立评测数据库，不能直接使用已经扩充演示数据的公网数据库。
- 正式生产还需要独立对象存储备份、外部告警、真实 Secrets、压测和安全审计。
