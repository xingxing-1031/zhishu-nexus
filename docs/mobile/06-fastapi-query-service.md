# 卡片 06：FastAPI 业务查询服务主链路

## 这张卡需要学到什么程度

本阶段不要求脱离资料重写所有代码，也不要求背诵 `Annotated`、`Depends`、`Mock` 等固定语法。

读完后需要能够：

1. 说清客户端请求如何经过 FastAPI、查询函数和 PostgreSQL，再变成 JSON。
2. 说清 `settings.py`、`database.py`、`queries.py`、`models.py`、`app.py` 的职责。
3. 看懂统计 SQL 的筛选、连接、分组、聚合、排序和限制。
4. 解释参数化 SQL、参数范围限制和三类测试为什么存在。
5. 准确说明当前只是固定业务查询服务，还不是完整 Agent。

## 先回答最关键的问题：app.py 在做什么

你的理解基本正确：`app.py` 主要负责定义 HTTP 接口，并调用其他模块已经写好的功能。

例如商品统计接口收到请求后，会调用 `queries.py` 中的：

```python
get_product_sales_summary(connection, days=days, limit=limit)
```

它们的关系是：

```text
app.py
  负责接口地址、HTTP 参数、数据库依赖和响应模型
        |
        v
queries.py
  负责业务 SQL、查询参数检查和结果模型转换
        |
        v
database.py
  提供可以与 PostgreSQL 通信的连接
        |
        v
PostgreSQL
  真正执行 SQL 并返回数据
```

`app.py` 不是把所有代码重新实现一次。它像一个接口入口：接收外部请求，准备参数和连接，调用查询服务，再把结果交回客户端。

## 五个文件的职责

### settings.py：读取连接配置

它从 `.env` 读取数据库地址、端口、数据库名、用户和密码，并校验配置类型。

它不执行 SQL，也不定义接口。

### database.py：建立和关闭数据库连接

它使用配置连接 PostgreSQL，并让查询结果以字典形式返回。

`get_database_connection()` 可以被 FastAPI 的 `Depends` 使用，在一次请求结束后关闭连接。

它不保存业务 SQL。

### queries.py：业务查询服务

它保存参数化 SQL 和查询函数，例如：

- `get_channel_sales_summary()`
- `get_product_sales_summary()`
- `get_refund_status_summary()`
- `get_order_status_summary()`

每个查询函数主要做三件事：检查参数、执行 SQL、把数据库结果转换成 Pydantic 模型。

### models.py：数据结构和边界

它定义请求或响应必须包含哪些字段、字段是什么类型、允许哪些状态以及数值边界。

例如 `ProductSalesSummary` 要求结果包含商品编号、商品名称、销量和销售额。

### app.py：HTTP 接口入口

它定义请求地址和方法，接收 URL 参数，通过 `Depends` 获得连接，调用 `queries.py`，并按 `response_model` 返回 JSON。

## 商品接口的完整链路

客户端发送：

```http
GET /analytics/products?days=30&limit=10
```

完整过程：

```text
1. FastAPI 根据路径找到 app.py 中的商品接口函数
2. Query 检查 days 是否在 1 到 365，limit 是否在 1 到 100
3. Depends 调用 get_database_connection() 获取数据库连接
4. app.py 调用 get_product_sales_summary()
5. queries.py 再次检查参数并执行参数化 SQL
6. PostgreSQL 连接订单明细、订单和商品三张表
7. PostgreSQL 返回商品销量和销售额
8. ProductSalesSummary 校验每行结果
9. FastAPI 把结果序列化为 JSON
10. 客户端收到 HTTP 200 和统计数据
```

FastAPI 和查询函数都检查参数不是毫无意义的重复：接口层负责保护 HTTP 边界；查询函数也可能被脚本、测试或其他 Python 代码直接调用，因此服务层需要保护自己的边界。

## 为什么商品统计连接三张表

商品销售统计需要的信息分散在三张表：

| 表 | 本次查询需要的信息 |
|---|---|
| `order_items` | 商品编号、购买数量、成交价快照 |
| `orders` | 订单是否已支付、订单时间 |
| `products` | 商品名称 |

因此它需要：

```sql
FROM order_items AS oi
JOIN orders AS o
    ON o.order_id = oi.order_id
JOIN products AS p
    ON p.product_id = oi.product_id
```

随后：

- `WHERE` 只保留最近指定天数的已支付订单。
- `GROUP BY` 把同一种商品放到一组。
- `SUM(quantity)` 计算销量。
- `SUM(quantity * unit_price)` 使用成交价快照计算销售额。
- `ORDER BY` 按销售额从高到低排序。
- `LIMIT` 只返回前 N 种商品。

## 四类统计的业务口径

### 渠道销售统计

只统计 `paid` 订单，因为指标是实际销售额。未支付、取消订单不能算作销售。

### 商品销售统计

只统计最近的已支付订单，按商品汇总数量和成交金额。历史金额读取 `order_items.unit_price`，不能使用可能已经改变的商品当前价格。

### 退款状态统计

按 `requested`、`approved`、`rejected`、`completed` 汇总记录数和金额。只有 `completed` 表示退款已经实际完成，其他状态仍是申请过程中的金额。

### 订单状态统计

为了观察订单状态分布，需要保留 `paid`、`pending`、`cancelled`、`shipped`、`completed`。这里汇总的是订单金额，不能把所有状态的金额都称为销售额。

## 为什么 SQL 参数不能直接拼接

项目使用：

```python
connection.execute(SQL, {"days": days, "limit": limit})
```

SQL 中使用：

```sql
%(days)s
%(limit)s
```

数据库驱动会把 SQL 结构和参数值分开处理。用户输入只能作为值，不能轻易变成额外的 SQL 结构，因此可以降低 SQL 注入风险，并统一处理类型转换。

错误示例是把用户输入直接拼入 SQL：

```python
sql = "SELECT ... LIMIT " + user_input
```

即使已经限制 `days` 和 `limit` 的范围，也仍应使用参数化 SQL。范围校验解决“数值是否合理”，参数化解决“输入不能改变 SQL 结构”，两者职责不同。

## days 和 limit 为什么需要边界

- `days` 最少为 1，防止没有意义的零天或负数查询；最多为 365，防止一次扫描过大时间范围。
- `limit` 最少为 1，保证能够返回结果；最多为 100，防止返回数据过多，增加数据库、网络以及以后大模型上下文的负担。

默认值只在用户不传参数时使用。用户明确传入非法值时，应该返回错误，不能偷偷改成默认值。

## 三类验证不能互相替代

### 查询函数测试

通常使用 `Mock` 数据库连接，验证：

- SQL 常量是否正确传入。
- `days/limit` 参数是否正确传入。
- 字典结果是否转换成正确模型。
- 非法参数是否在访问数据库前被拒绝。

它不证明真实 PostgreSQL 正在运行。

### FastAPI 接口测试

使用 `TestClient`，并通过 `dependency_overrides` 替换真实数据库连接，验证：

- 路由是否存在。
- URL 参数是否合法。
- HTTP 状态码是否正确。
- 响应是否正确序列化为 JSON。

它不经过真实网络，也不一定访问真实数据库。

### 真实集成检查

不使用 Mock，让 FastAPI、psycopg 和 PostgreSQL 连成完整链路。它能发现账号、密码、端口、数据库状态、真实 SQL 等集成问题。

本阶段四个真实统计接口均返回 HTTP `200`，完整自动化测试为 `38 passed`。

## 遇到报错时先判断哪一层

| 现象 | 优先检查 |
|---|---|
| `NameError`、导入未定义 | Python 导入和命名 |
| URL 参数错误返回 `422` | FastAPI/Pydantic 参数校验 |
| SQL 列名或分组错误 | `queries.py` 中的 SQL |
| 连接拒绝、密码错误 | `.env`、`settings.py`、`database.py`、PostgreSQL |
| 返回字段缺失或类型错误 | SQL 别名和响应模型 |
| Mock 测试通过但真实查询失败 | 数据库集成、真实数据或 SQL 方言 |

## 当前还不是完整 Agent

现在完成的是“不依赖大模型的固定业务查询服务”。它为 Agent 提供可靠的数据执行基础，但还没有：

- 根据自然语言自动制定分析计划。
- 根据指标知识和表结构进行 RAG 检索。
- 生成并使用 AST 校验任意只读 SQL。
- LangGraph 工作流和中断恢复。
- 完整查询 Trace、权限、人工审批和评测集。

因此当前准确表述是：已经完成 FastAPI 到 PostgreSQL 的固定统计查询链路，尚未完成自然语言驱动的 Agent 闭环。

## 自测

### 1. app.py 和 queries.py 是什么关系？

<details>
<summary>展开标准答案</summary>

`app.py` 定义 HTTP 路由、解析和校验接口参数、获取数据库依赖并规定响应模型；它调用 `queries.py` 中的业务查询函数。`queries.py` 负责参数化 SQL、服务层参数边界、执行查询和结果模型转换。接口层不需要重新实现查询逻辑。

</details>

### 2. 商品统计请求怎样变成 JSON？

<details>
<summary>展开标准答案</summary>

FastAPI 匹配商品路由并校验 `days/limit`，`Depends` 提供数据库连接，接口调用商品查询函数；查询函数让 PostgreSQL 执行三表参数化 SQL，数据库返回字典行；Pydantic 响应模型校验结果，FastAPI 将其序列化成 JSON 并返回 HTTP 200。

</details>

### 3. 为什么渠道销售额只统计 paid，而订单状态汇总保留 cancelled？

<details>
<summary>展开标准答案</summary>

渠道接口回答实际销售额，未支付和取消订单不能算销售；订单状态接口回答状态分布，取消订单本身就是运营需要观察的数据，所以必须保留。后者的金额应称为订单金额，而不是全部称为销售额。

</details>

### 4. 参数范围校验能否替代参数化 SQL？

<details>
<summary>展开标准答案</summary>

不能。范围校验判断数值是否符合业务限制；参数化 SQL 把 SQL 结构与输入值分开，避免输入改变 SQL 结构并降低注入风险。两者解决的问题不同，应同时存在。

</details>

### 5. 为什么 Mock 测试通过后还要真实集成检查？

<details>
<summary>展开标准答案</summary>

Mock 只模拟数据库返回结果，适合验证函数调用和转换逻辑，但不会发现数据库没有启动、密码错误、表不存在或真实 SQL 无法执行。真实集成检查能够验证 FastAPI、驱动和 PostgreSQL 的完整连接。

</details>

## 三分钟口述参考结构

不要背原句，按照以下因果顺序说明：

1. 项目为运营人员提供订单、商品、渠道和退款四类固定统计接口。
2. 配置层读取数据库配置，连接层管理 PostgreSQL 连接，查询层执行参数化业务 SQL，模型层约束输入输出，接口层接收 HTTP 请求并调用查询服务。
3. 以商品查询为例，说明参数校验、依赖连接、三表 JOIN、已支付和时间筛选、分组聚合、Pydantic 校验和 JSON 返回。
4. 说明参数化 SQL 与 `days/limit` 边界各自解决什么问题。
5. 说明查询测试、接口测试和真实集成检查的区别。
6. 最后说明当前仍未实现自然语言 Agent、RAG、SQL AST 安全校验和审计 Trace。

## 三分钟口述标准答案

> 我正在开发一个面向零售运营的可审计数据分析 Agent。W2-2 解决的是 Python 后端如何连接真实 PostgreSQL，并把固定的业务统计能力通过 FastAPI 提供给客户端。目前完成了四类统计接口：渠道销售统计、商品销售统计、退款状态统计和订单状态统计。运营人员或以后 Agent 的工作流可以通过这些接口获得真实数据库结果，而不需要把 SQL 直接写在接口代码里。
>
> 这部分代码按照职责拆成了几个模块。`settings.py` 负责从 `.env` 读取并校验数据库连接配置；`database.py` 通过 psycopg 建立和关闭数据库连接，并使用 `dict_row` 把结果转换成以列名为键的字典；`queries.py` 保存参数化业务 SQL 和查询函数，负责检查参数、执行查询并转换响应模型；`models.py` 定义请求和响应的数据结构；`app.py` 定义 FastAPI 路由、接收 HTTP 参数、通过 `Depends` 获取数据库连接、调用查询函数，并把结果转换成 JSON 返回客户端。
>
> 以商品统计为例，客户端发送 `GET /analytics/products?days=30&limit=10`。FastAPI 先匹配路由并校验参数，然后 `Depends` 提供数据库连接，接口调用 `get_product_sales_summary()`。查询函数连接订单明细、订单和商品三张表，只保留最近指定天数的已支付订单，按照商品分组，使用订单明细中的成交价快照计算销量和销售额，再按照销售额降序排序并限制返回数量。PostgreSQL 返回字典结果后，`ProductSalesSummary` 校验字段，FastAPI 最终返回 HTTP `200` 和 JSON 数据。
>
> SQL 使用 `%(days)s`、`%(limit)s` 和参数字典，不直接拼接用户输入。参数化查询把 SQL 结构和参数值分开处理，可以降低 SQL 注入风险；`days` 和 `limit` 的范围限制用于拒绝不合理查询和控制资源消耗，两者职责不同。
>
> 查询函数测试使用 Mock，验证 SQL、参数、模型转换和非法参数；接口测试使用 TestClient，验证路由、HTTP 状态码和 JSON，但通常不访问真实数据库，也不经过真实网络；真实集成检查不使用 Mock，验证 FastAPI、psycopg 和 PostgreSQL 的完整链路。目前完整测试为 `38 passed`，四个真实统计接口均返回 HTTP `200`。
>
> 当前完成的是固定参数化业务查询服务，是 Agent 的数据执行基础，但还没有完成 SQL AST 只读校验、自然语言分析计划、LangGraph 工作流、RAG 检索、权限控制和完整审计 Trace，后续阶段会继续实现这些能力。

不要求逐字背诵。关闭页面后能用自己的语言讲清模块职责、商品查询链路、参数化 SQL、三类测试和当前边界，就达到了本阶段要求。

能不看卡片说清上述关系，就达到了 W2-2 当前需要的理解深度。
