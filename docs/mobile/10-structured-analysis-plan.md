# Pydantic 结构化分析计划

## W3-2 解决什么问题

W3-1 已经建立 LangGraph 工作流骨架，但当时 `AnalysisState.plan` 的类型是：

```python
dict[str, object] | None
```

普通字典没有稳定契约。计划节点可能返回 `metric`，也可能误写成 `metrics_name`；可能把销售额写成指标，也可能写入项目没有支持的利润指标。后面的检索和 SQL 生成节点无法可靠使用这种结果。

W3-2 将它改成：

```python
AnalysisPlan | None
```

`AnalysisPlan` 是 Pydantic 模型。它把一次自然语言分析请求拆成固定字段，并在计划进入后续节点前进行校验。

## 从自然语言到结构化计划

用户问题：

```text
最近 30 天各渠道已支付订单的销售额，
按照销售额从高到低排列，最多返回 10 行。
```

对应的计划结构：

```text
analysis_goal: 统计最近30天各渠道已支付订单的销售额
metrics: [sales_amount]
dimensions: [channel]
filters:
  - field: order_status
    operator: equals
    value: paid
time_range:
  days: 30
sort:
  - field: sales_amount
    direction: descending
limit: 10
```

### 指标 Metric

指标是最终需要计算的数值，例如：

- `sales_amount`：销售额。
- `order_count`：订单数。
- `units_sold`：商品销量。
- `refund_amount`：退款金额。
- `refund_count`：退款数量。
- `average_order_value`：客单价。

“销售额是多少”中的销售额是指标。

### 维度 Dimension

维度决定结果按照什么拆分或分组，例如：

- `channel`：按渠道分组。
- `product`：按商品分组。
- `category`：按商品类别分组。
- `order_status`：按订单状态分组。
- `refund_status`：按退款状态分组。
- `day`：按天分组。

“各渠道销售额”中的渠道是维度。没有维度时，可以只返回一个整体汇总值。

### 筛选 Filter

筛选条件决定哪些原始记录可以参与计算：

```text
order_status equals paid
```

表示只让已支付订单进入后续销售额聚合。

当前支持两个操作符：

- `equals`：值必须是单个标量，例如 `paid`。
- `in`：值必须是非空列表，例如 `[taobao, jd]`。

### 时间、排序和行数

- `time_range.days`：当前支持最近 1 至 365 天。
- `sort`：排序字段必须已经出现在本次指标或维度中。
- `limit`：允许 1 至 1000，默认 100。

排序字段受限可以防止计划要求“按一个没有计算、也没有返回的字段排序”。

## 枚举为什么重要

指标、维度、筛选字段、筛选操作符和排序方向都使用 `StrEnum`。例如指标只能从已经支持的指标中选择：

```text
sales_amount
order_count
units_sold
refund_amount
refund_count
average_order_value
```

如果模型生成 `profit`，Pydantic 会拒绝计划。拒绝未知值比让 SQL 生成节点自行猜测利润口径更安全，也更容易审计和排错。

## 为什么禁止额外字段

计划模型设置了：

```python
ConfigDict(extra="forbid")
```

如果模型输出计划定义之外的字段，例如把 `generated_sql` 直接塞进分析计划，Pydantic 会抛出 `ValidationError`。

这可以发现字段拼写错误、模型擅自扩展结构和版本不一致。它不是为了证明额外字段一定危险，而是为了保持节点之间的契约明确。

## 字段规则与跨字段规则

字段规则只检查一个字段自身，例如：

```text
days 必须在 1 到 365 之间
limit 必须在 1 到 1000 之间
metrics 至少有一项
```

跨字段规则需要同时观察多个字段，例如：

```text
equals 不能配列表值
in 必须配非空列表
指标和维度不能重复
排序字段必须已经被选为指标或维度
```

项目使用 `model_validator` 实现这些跨字段关系。

## Pydantic 校验不等于 SQL 安全

结构化计划校验解决的是“分析意图是否符合项目支持的计划格式”。它不能证明以后生成的 SQL 安全。

后续仍然需要：

```text
AnalysisPlan 校验
-> 检索指标与 Schema 证据
-> 生成 SQL
-> SQLGlot AST 与白名单校验
-> PostgreSQL 只读、超时和行数限制
-> 审计
```

例如，一个合法计划要求统计销售额，但 SQL 节点仍可能错误生成 `DELETE`，所以 W2-3 和 W2-4 的安全防线不能被 Pydantic 替代。

## 与 LangGraph State 的关系

`AnalysisState` 现在保存：

```python
plan: AnalysisPlan | None
```

初始状态时 `plan=None`。计划节点成功后写入 `AnalysisPlan`，后面的检索和 SQL 生成节点就可以读取稳定字段，而不需要猜测普通字典里有什么键。

当前测试中的计划节点仍是假节点，它直接创建一个固定 `AnalysisPlan`。这证明工作流可以传递结构化计划，但不证明真实大模型已经接入。

## 当前测试证明什么

W3-2 新增测试覆盖：

- 合法业务问题能够形成结构化计划。
- 未知指标被拒绝。
- 指标不能为空。
- 最近天数必须在 1 至 365 范围内。
- 未定义的额外字段被拒绝。
- `equals` 与 `in` 的值类型必须匹配。
- 排序字段必须已被选择。
- 重复指标被拒绝。
- 数值筛选值不会被错误丢失。
- W3-1 工作流可以传递 `AnalysisPlan`。

这些测试证明模型契约和当前 State 接入正确，不证明模型能够从任意自然语言稳定生成正确计划。

## 当前边界

- 尚未调用任何大模型 API。
- 没有真实计划节点，测试使用固定结构化数据。
- 当前时间范围只支持“最近 N 天”，尚未支持明确的开始和结束日期。
- 当前筛选操作只支持 `equals` 和 `in`。
- 计划合法不代表 SQL 正确或安全。
- W3-3 才会把检索、SQL 校验和查询服务封装为真实工具节点。

## 自测

### 1. 为什么不能继续使用普通字典保存计划？

<details>
<summary>查看答案</summary>

普通字典不能稳定限制字段名、字段类型和业务关系。后续节点需要猜测结构，也无法及时发现未知指标、拼写错误或额外字段。Pydantic 模型提供明确契约和结构化错误。

</details>

### 2. 指标、维度和筛选有什么区别？

<details>
<summary>查看答案</summary>

指标是要计算的数值；维度决定按什么分组；筛选决定哪些原始记录可以参与计算。例如“各渠道已支付订单的销售额”中，销售额是指标，渠道是维度，已支付是筛选。

</details>

### 3. 为什么 `in` 必须使用非空列表？

<details>
<summary>查看答案</summary>

`in` 表示允许多个候选值，因此需要列表；空列表没有任何候选条件，也通常无法表达有意义的业务筛选。单值比较应使用 `equals`。

</details>

### 4. 为什么排序字段必须已经出现在指标或维度中？

<details>
<summary>查看答案</summary>

结果只能稳定地按照已经计算或返回的字段排序。限制排序字段可以避免计划引用没有定义、没有计算或无法解释的字段。

</details>

### 5. `extra="forbid"` 解决什么问题？

<details>
<summary>查看答案</summary>

它拒绝模型契约之外的字段，可以尽早暴露字段拼写错误、模型擅自扩展输出和不同版本之间的结构不一致。

</details>

### 6. AnalysisPlan 校验通过后，为什么仍需要 SQLGlot？

<details>
<summary>查看答案</summary>

AnalysisPlan 只证明分析意图符合结构化契约。SQL 是后续另外生成的执行指令，仍可能包含错误表、危险语句或越权字段，所以必须继续经过 AST、白名单、只读事务、超时和审计防线。

</details>

### 7. 当前假计划节点能证明什么？

<details>
<summary>查看答案</summary>

它证明 `AnalysisPlan` 可以被创建、校验并通过 LangGraph State 传递。它不能证明真实大模型能够正确理解自然语言或稳定生成计划。

</details>

## 两分钟口述提纲

1. W3-2 为什么把普通字典换成 Pydantic 模型。
2. 指标、维度、筛选、时间、排序和行数分别表示什么。
3. 枚举、字段边界、`extra="forbid"` 和跨字段校验解决什么问题。
4. `equals` 与 `in` 的区别。
5. `AnalysisPlan` 怎样进入 `AnalysisState`。
6. 为什么计划校验不能替代 SQL 安全校验。
7. 当前没有真实大模型和真实计划节点。
