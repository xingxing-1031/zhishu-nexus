# 卡片 05：PostgreSQL、Docker 与 pgvector

> 这是 W2-1 预习卡。阅读后只要求形成概念地图，不算已经完成数据库实操。

## PostgreSQL 是什么

PostgreSQL 是关系型数据库管理系统。它负责长期保存订单等数据，并提供表、约束、事务、索引和 SQL 查询能力。

项目之前写的 SQL 只是文件里的查询设计。只有建立真实数据库、创建表、导入数据并实际执行后，才能证明 SQL 对当前表结构和数据有效。

## pgvector 是什么

pgvector 是 PostgreSQL 的一个扩展，让 PostgreSQL 能保存向量并执行相似度检索。以后做指标字典和 Schema RAG 时可以使用它。

两者关系是：

```text
PostgreSQL：数据库主体，先保存结构化业务数据
pgvector：可选扩展，后来增加向量检索能力
```

当前 W2-1 的重点是 PostgreSQL 表结构、迁移和种子数据，不是立即开发 RAG。

## Docker 在这里做什么

Docker 用容器运行 PostgreSQL，让项目环境更容易复现。需要区分四个概念：

- 镜像（image）：创建容器的只读模板，可以理解为安装包加运行环境。
- 容器（container）：由镜像启动的一个运行实例。
- 端口映射（port）：把电脑端口连接到容器内数据库端口，例如主机 `5432` 到容器 `5432`。
- 数据卷（volume）：把数据库数据持久保存到容器生命周期之外，重建容器时避免数据一起消失。

Docker Desktop 是 Windows 上管理 Docker 引擎、WSL2 集成和容器的工具。安装 Docker 不等于数据库已经启动；还需要拉取镜像并启动 PostgreSQL 容器。

## 迁移与种子数据

- 迁移（migration）：用可追踪的版本脚本创建或修改数据库结构，例如新增表、列、约束和索引。
- 种子数据（seed data）：一组可重复导入的示例业务数据，用于本地开发和自动化测试。

直接手工点数据库界面建表难以复现。迁移和种子脚本能让另一台电脑按相同步骤得到相同结构和基础数据。

## W2-1 真正要完成的证据

```text
Docker 中 PostgreSQL 可启动
-> 迁移能从空数据库创建四张表和约束
-> 种子数据可重复导入
-> SQL 能在真实数据库执行
-> 自动化测试或命令输出保存为证据
```

在这些证据出现前，不能写“已接入 PostgreSQL”或“真实 SQL 已验证”。

## 自测

### 1. PostgreSQL 和 pgvector 是同一个东西吗？

<details>
<summary>展开标准答案</summary>

不是。PostgreSQL 是关系型数据库主体；pgvector 是安装在 PostgreSQL 中的扩展，为它增加向量存储和相似度检索能力。

</details>

### 2. Docker Desktop 安装完成是否等于 PostgreSQL 已经运行？

<details>
<summary>展开标准答案</summary>

不等于。Docker Desktop 只提供容器运行和管理环境，还要准备 PostgreSQL 镜像、配置端口和数据卷，并实际启动容器。

</details>

### 3. 为什么数据库需要数据卷？

<details>
<summary>展开标准答案</summary>

容器本身可以删除和重建。数据卷把数据库文件持久保存在容器生命周期之外，避免重建容器时业务数据随容器消失。

</details>

### 4. 迁移和种子数据分别解决什么问题？

<details>
<summary>展开标准答案</summary>

迁移用版本化脚本复现数据库结构及其变化；种子数据提供可重复导入的基础业务数据，便于开发、测试和演示。

</details>

## 1 分钟口述

用“数据库主体、扩展、镜像、容器、端口、数据卷、迁移、种子数据”八个词，说明下一阶段要搭建的环境。
