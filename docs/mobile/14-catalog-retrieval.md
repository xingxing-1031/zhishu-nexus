# W4-2 手机学习卡：按分析计划检索业务证据

## 1. 本阶段解决什么问题

W4-1 已经建立指标字典和 Schema 目录，但它们只是静态知识。若不接入工作流，后面的 SQL 生成节点仍然拿不到这些业务依据。

W4-2 新增真实目录检索工具，把结构化分析计划转换成当前任务所需的指标、表和 JOIN 证据：

```text
AnalysisState.plan
→ CatalogRetrievalTool.retrieve()
→ 指标证据 + 表证据 + JOIN 证据
→ AnalysisState.retrieved_context
```

## 2. 为什么不把全部目录交给模型

全部 6 个指标、4 张表和 3 条 JOIN 都交给模型，会增加 Token、延迟和干扰项。模型还可能从无关定义中选择错误指标或增加不必要的 JOIN。

W4-2 采用“最小充分证据”：

```text
最小：不返回本次分析不需要的知识
充分：返回完成本次分析所需的全部指标、字段和连接关系
```

较小且相关的上下文也更容易审计，可以准确记录这次分析依据了哪个指标版本、哪些表和哪些 JOIN。

## 3. 为什么同时分析指标、维度和筛选

三个部分承担不同职责：

```text
指标 metric：算什么，例如销售额
维度 dimension：按什么分组，例如商品
筛选 filter：哪些原始记录参与计算，例如指定商品 P001
```

指标本身只决定基础来源。维度和筛选可能引入新表。例如销售额来源于 `orders` 和 `order_items`，但“按商品统计”还需要 `products`。

因此检索不能只看指标，必须合并三个部分需要的表，再寻找它们之间的批准连接路径。

## 4. 商品销售额示例

分析计划：

```text
metrics = [sales_amount]
dimensions = [product]
```

最小充分证据：

```text
metric.sales_amount.v1
schema.orders
schema.order_items
schema.products
schema.join.orders.order_items
schema.join.products.order_items
```

销售额使用 `order_items.quantity * order_items.unit_price`，并通过 `orders.status` 应用已支付规则。按商品分组还要读取商品信息，所以需要经过订单明细连接 `products`。

`orders` 和 `products` 没有直接对应关系。`order_items` 同时保存 `order_id`、`product_id`、购买数量和成交价快照，是两者之间的关联表和销售额计算来源。

## 5. 退款状态示例

分析计划：

```text
metrics = [refund_amount]
dimensions = [refund_status]
```

最小充分证据只有：

```text
metric.refund_amount.v1
schema.refunds
```

退款金额在 `refunds.refund_amount`，退款状态在 `refunds.status`。计算与分组字段都在一张表中，因此不需要商品表、订单明细表或 JOIN。

## 6. 数据库能 JOIN 不代表业务允许

当前 `refunds` 只关联主订单，没有记录退款对应哪条订单明细。若一个订单有 3 个商品和一笔 300 元退款，强行连接商品后，同一退款可能匹配 3 行并被错误计算成 900 元。

因此 `refund_amount.v1` 目前只支持 `refund_status` 和 `day`，不支持 `product`。遇到“按商品统计退款金额”，工具直接拒绝，不能根据存在的数据库路径猜测业务含义。

未来若要支持商品退款分析，需要增加退款明细，例如：

```text
refund_id
order_item_id
product_id
refund_quantity
refund_amount
```

## 7. 维度校验做什么

`_validate_dimensions()` 会比较分析计划的维度与每个指标的 `supported_dimensions`。

```text
支持：继续检索
不支持：抛出 CatalogRetrievalToolError
```

这属于业务能力校验，不是 SQL 安全校验。它在生成 SQL 之前阻止没有可靠业务口径的分析计划。

## 8. JOIN 路径怎样选择

工具先收集必需表，再只使用 `SchemaCatalog` 中批准的 JOIN 寻找最短连接路径。

```text
orders → order_items → products
orders → refunds
```

`_find_required_join_indexes()` 负责确定需要哪些 JOIN；`_shortest_join_path()` 负责查找连接路径。学习阶段只需理解它们的用途，不要求背诵或手写路径搜索算法。

工具不会自行发明 JOIN，也不会因为某张表存在就把它加入证据。

## 9. 证据怎样进入 Agent 状态

指标、表和 JOIN 定义都会转换为统一的 `RetrievalEvidence`：

```text
source_id：证据的稳定来源编号
content：提供给后续节点的业务说明
```

真实检索节点执行：

```text
tool.retrieve(state["plan"])
→ state["retrieved_context"]
```

后续 SQL 生成节点可以读取这些证据，审计系统也能记录本次分析实际使用了哪些来源。

## 10. 当前检索是不是 RAG

当前是确定性的目录检索，不是向量 RAG：

```text
输入：已经结构化的 AnalysisPlan
选择：枚举值、指标目录和 Schema 关系
输出：确定且可重复的证据集合
```

它不需要大模型，也没有使用 Embedding、向量数据库或语义相似度。W4-3 会评估检索覆盖率和干扰情况；W4-4 才接入真实模型，让自然语言产生计划并使用证据生成 SQL。

## 11. 测试证明了什么

本阶段新增 6 项测试，覆盖：

```text
商品销售返回三张表和两条 JOIN
退款状态只返回 refunds
多个指标共用证据时自动去重
筛选字段引入新表和批准 JOIN
不支持的指标维度组合被拒绝
真实检索节点把证据写入 state
```

全量回归结果是 `121 passed`。

这些测试证明目录检索和工作流状态传递符合预期，但不证明真实模型能够正确理解所有自然语言，也不证明模型生成 SQL 的准确率。

## 12. 自测题

1. W4-1 和 W4-2 的区别是什么？
2. 什么是“最小充分证据”？
3. 为什么不能把全部指标和 Schema 一次性交给模型？
4. 指标、维度和筛选分别决定什么？
5. 为什么检索不能只看指标？
6. 按商品统计销售额需要哪些表和 JOIN？
7. 按退款状态统计退款金额为什么只需要退款表？
8. 数据库存在 JOIN 路径为什么不代表业务允许这样计算？
9. 为什么当前退款金额不支持商品维度？
10. `RetrievalEvidence` 中 `source_id` 的作用是什么？
11. 当前目录检索和向量 RAG 有什么区别？
12. 121 项测试通过后，仍然不能证明什么？

## 13. 自测题标准答案

### 1. W4-1 和 W4-2 的区别是什么？

W4-1 定义和保存版本化指标、表、字段及 JOIN 知识；W4-2 根据当前分析计划选择相关知识，并通过真实检索节点写入工作流状态。

### 2. 什么是“最小充分证据”？

只返回完成当前分析所需的知识，不加入无关定义，同时保证必要的指标公式、表结构和 JOIN 关系没有缺失。

### 3. 为什么不能把全部指标和 Schema 一次性交给模型？

全部内容会增加 Token、延迟和干扰项，模型可能选错指标、字段或 JOIN。按计划检索更快、更准确，也更容易审计和评估。

### 4. 指标、维度和筛选分别决定什么？

指标决定计算什么结果，维度决定结果按什么分组，筛选决定哪些原始业务记录参与计算。

### 5. 为什么检索不能只看指标？

维度和筛选可能需要指标来源之外的字段和表。例如销售额本身使用订单和明细，但按商品分组还需要商品表及其 JOIN。

### 6. 按商品统计销售额需要哪些表和 JOIN？

需要 `orders`、`order_items`、`products`；需要 `orders.order_id = order_items.order_id` 和 `products.product_id = order_items.product_id`。

### 7. 按退款状态统计退款金额为什么只需要退款表？

退款金额和退款状态都在 `refunds` 中，一张表已经同时提供计算和分组字段，不需要额外表或 JOIN。

### 8. 数据库存在 JOIN 路径为什么不代表业务允许这样计算？

数据库路径只说明记录能够关联，不保证关联后的粒度和计算含义正确。一对多连接可能复制行、重复金额或把订单级数据错误分配给商品。

### 9. 为什么当前退款金额不支持商品维度？

当前退款记录只关联主订单，没有保存退款对应的订单明细、商品、退款数量和商品级退款金额，因此无法可靠地把退款分配到具体商品。

### 10. `RetrievalEvidence` 中 `source_id` 的作用是什么？

它稳定标识具体指标版本、表或 JOIN，让后续 SQL 生成依据和审计记录能够回溯到唯一知识来源。

### 11. 当前目录检索和向量 RAG 有什么区别？

当前检索根据结构化枚举和目录关系确定性选择证据，不使用 Embedding 或相似度；向量 RAG 根据文本语义相似度从大量非结构化知识中召回内容。

### 12. 121 项测试通过后，仍然不能证明什么？

不能证明真实大模型能够正确理解所有自然语言、稳定生成正确计划和 SQL，也不能证明端到端 Agent 已经完成。
