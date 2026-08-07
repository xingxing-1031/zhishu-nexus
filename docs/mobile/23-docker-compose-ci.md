# W6-3 手机学习卡：Docker Compose、pytest 与 GitHub Actions

## 这一步解决什么问题？

前面的功能和评测主要证明项目在当前电脑上可用。W6-3 要解决的是可重复交付：换一台电脑或收到一次 Git 提交后，系统能够用同一份配置创建数据库、执行测试，并尽早暴露迁移缺失、依赖不兼容或代码回归。

## Docker、镜像、容器、卷和 Compose 的关系

```text
Dockerfile/镜像：可复用的运行环境模板
容器：镜像的一次运行实例
数据卷：独立于容器生命周期保存 PostgreSQL 数据
Compose：用 compose.yaml 统一声明镜像、环境变量、端口、卷、初始化文件和健康检查
```

本项目直接使用 `pgvector/pgvector:pg16` 镜像。Compose 启动 PostgreSQL 容器，把本地迁移和种子脚本只读挂载到 `/docker-entrypoint-initdb.d/`，并用命名卷 `postgres_data` 保存真实数据库文件。

## 为什么初始化脚本只在空数据卷执行？

这是 PostgreSQL 官方镜像入口脚本的规则：只有数据库目录为空时，才创建数据库并按文件名顺序执行 `/docker-entrypoint-initdb.d/` 中的脚本。已有数据卷再次 `docker compose up` 时不会重跑这些文件。

这样可以避免每次重启都重复初始化或覆盖已有数据，但也意味着新增迁移文件不会自动应用到旧卷。开发中的旧数据库仍需显式执行新迁移；要测试“从零交付”，应使用独立 Compose 项目和临时空卷。

本项目初始化顺序是：

```text
001_initial_schema.sql
002_query_audit_logs.sql
003_knowledge_chunks.sql
004_query_approval_logs.sql
005_resilience_and_idempotency.sql
006_execution_trace.sql
007_demo_data.sql
```

最后一个文件在仓库中原名是 `db/seeds/001_demo_data.sql`，挂载进容器时改名为 `007_demo_data.sql`，保证它在所有表迁移之后执行。

## healthcheck 和 `--wait` 分别做什么？

`healthcheck` 在容器内部运行 `pg_isready`，检查 PostgreSQL 是否已经接受连接。`docker compose up -d --wait` 会等服务进入 healthy 状态再返回，避免后续命令过早连接数据库。

但 healthy 只等于“数据库能连接”，不等于“表、扩展和种子数据都正确”。因此 CI 还会执行 `verify_delivery.sql`，检查 pgvector、交付所需关系、审计幂等字段和 10 条演示订单。

## pytest 和 GitHub Actions 的职责有什么不同？

`pytest` 是测试框架，负责执行具体的 Python 测试并报告通过或失败。它可以在本地运行，也可以在 CI 中运行。

GitHub Actions 是自动化执行环境。每次向 `main` 推送或创建 Pull Request 时，它会根据 `.github/workflows/ci.yml` 创建全新的 runner：

```text
python-tests：分别用 Python 3.11 和 3.12 安装项目并运行完整 pytest
postgres-smoke：校验 Compose，创建全新 pgvector 数据库，再执行交付验收 SQL
```

测试矩阵可以发现代码只兼容某个 Python 版本的问题。真实 PostgreSQL smoke 可以发现 Mock 测试看不到的镜像、挂载、迁移顺序、SQL 方言、扩展和种子初始化问题。

## 本地测试和 CI 的边界

本地验证反馈快，适合开发和定点排错；CI 使用干净环境，适合发现“只在我的电脑上能运行”的隐含依赖。CI 通过仍不等于生产部署完成，因为当前没有正式登录、密钥管理、云数据库、HTTPS、监控和生产备份。

本地开发卷保存已有数据，不能随便执行 `docker compose down -v`。`-v` 会删除命名卷，下一次启动会得到全新数据库。CI 使用的是临时数据，所以工作流结束时执行 `down --volumes` 是正确的清理行为。

## 三分钟口述提纲

1. W6-3 从“本机能运行”推进到“干净环境可重复验证”。
2. 镜像、容器、卷和 Compose 的职责。
3. 初始化脚本只对空数据卷执行，以及迁移顺序。
4. healthcheck、`--wait` 与验收 SQL 的区别。
5. pytest 与 GitHub Actions 的职责，以及 Python 版本矩阵。
6. 为什么 Mock 测试之外还要真实 PostgreSQL smoke。
7. 本地卷不能随便删除，CI 临时卷应在结束后清理。
8. 当前只是持续集成与本地交付，不等于生产部署。

## 三分钟口述标准参考

我正在开发一个面向零售运营人员的可审计分析 Agent。W6-3 的目标是把项目从“在当前电脑上可以运行”推进到“在干净环境中可以重复创建和验证”。本项目使用 pgvector 的 PostgreSQL 16 镜像，Docker 容器是镜像的一次运行实例，命名卷负责在容器重建后保留数据库文件，Docker Compose 则统一声明镜像、环境变量、端口、卷、迁移脚本和健康检查。

六个迁移文件和一个种子文件会被挂载到 PostgreSQL 镜像的初始化目录，并按文件名顺序执行。官方镜像只会在数据卷为空时执行这些初始化脚本，所以重启已有容器不会重复导入数据，也不会自动执行后来新增的迁移。旧数据库升级仍需显式运行迁移；验证从零交付时则使用独立项目和临时空卷。

健康检查使用 pg_isready 判断 PostgreSQL 是否已经接受连接，Compose 的 wait 参数会等待服务健康后再执行后续命令。但能连接不代表数据库内容正确，所以项目还有交付验收 SQL，检查 pgvector 扩展、业务表、审计和 Trace 等关系、幂等字段以及 10 条演示订单。

pytest 负责执行具体的 Python 测试；GitHub Actions 负责在每次推送和 Pull Request 时创建干净环境并自动调用这些检查。CI 分别在 Python 3.11 和 3.12 上运行 358 项回归测试，还会启动一套全新的 PostgreSQL，验证 Compose、迁移顺序和种子数据。Mock 测试适合快速验证 Python 逻辑，但不能证明真实镜像、扩展和 SQL 初始化正确，因此两类测试都需要。

本地开发卷保存真实开发数据，不能随便使用 down -v 删除；CI 数据卷只是一次运行的临时资源，结束时应删除，保证下次仍从空环境验证。当前完成的是本地可重复交付和持续集成，还不等于生产部署，因为正式身份认证、密钥管理、云端基础设施、监控和备份仍未完成。

## 自测题与标准答案

1. **为什么迁移和种子脚本只在空数据卷自动执行？** PostgreSQL 官方镜像只在首次初始化空数据库目录时运行 `/docker-entrypoint-initdb.d/`；这样避免重启时覆盖已有数据，但旧卷新增迁移必须显式执行。
2. **Docker Compose 在本项目中负责什么？** 它统一编排 pgvector 镜像、PostgreSQL 容器、环境变量、端口、数据卷、初始化脚本和健康检查，使本地与 CI 使用同一份数据库启动契约。
3. **pytest 与 GitHub Actions 分别负责什么？** pytest 定义并运行具体测试；GitHub Actions 在推送或 PR 时提供干净的自动化环境，安装项目并调用 pytest 和数据库 smoke。
4. **为什么 CI 不能只跑 Mock 测试？** Mock 不会真实启动 PostgreSQL，无法发现镜像、pgvector、挂载路径、迁移顺序、SQL 方言和种子初始化错误。
5. **`healthcheck` 通过为什么还要运行验收 SQL？** healthcheck 只证明 PostgreSQL 能接受连接；验收 SQL 才证明扩展、表结构、关键字段和种子数据符合交付要求。
6. **为什么本地不能随便执行 `docker compose down -v`？** `-v` 会删除保存 PostgreSQL 数据的命名卷，已有开发数据随之丢失；它只适合明确要重建的临时环境。
7. **Python 3.11 和 3.12 测试都通过证明了什么？** 证明当前代码和依赖在这两个声明支持的 Python 版本上通过同一套回归；不代表其他版本或生产环境自动兼容。
8. **CI 通过是否代表生产部署完成？** 不代表。CI 证明代码与交付配置在受控干净环境通过，还没有覆盖正式登录、密钥管理、云数据库、HTTPS、监控、备份和容量规划。
