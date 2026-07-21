# 卡片 02：Pydantic 与 pytest

## 类、对象与 BaseModel

```python
class Order(BaseModel):
    order_id: str
    amount: Decimal
```

- `class` 用于定义类。
- `Order` 是开发者起的类名，可以换成其他合法名称，但应表达业务含义。
- `BaseModel` 来自 Pydantic。继承它以后，`Order` 获得类型转换、数据校验和错误信息等能力。
- `Order(...)` 创建一个具体订单对象。大写 `Order` 通常表示类，小写 `order` 通常表示某个局部变量，这是命名习惯，不是 Python 强制语法。

## Pydantic 负责什么

Pydantic 位于数据进入业务逻辑的边界，负责：

- 把可转换的数据转成目标类型，例如字符串 `"99.90"` 转成 `Decimal("99.90")`。
- 检查范围，例如 `ge=0` 表示大于或等于 0，`gt=0` 表示严格大于 0。
- 限制状态值，例如只允许 `paid`、`pending` 等已定义状态。
- 输入不合法时抛出 `ValidationError`。

`ValidationError` 是一次校验失败的结构化错误，通常包含错误字段、位置、原因和收到的值。

## pytest 负责什么

pytest 不负责制定或执行 Pydantic 的业务规则。它负责运行测试，并检查实际行为是否符合预期。

```python
with pytest.raises(ValidationError):
    Order(order_id="o-1", amount=Decimal("-1"))
```

执行顺序是：

1. pytest 先声明“这段代码应该抛出 `ValidationError`”。
2. `Order(...)` 调用 Pydantic 校验。
3. Pydantic 发现负数违反规则并抛错。
4. pytest 收到预期类型的错误，因此测试通过。

如果 Pydantic 没有抛错，反而说明非法数据被接受，测试会失败。

## 为什么规则和测试都需要

规则负责在程序运行时拦截非法数据；测试负责防止以后修改代码时意外删掉或破坏规则。测试不是多做一遍业务校验，而是在验证校验能力长期存在。

测试单个非法字段时，其他必填字段应该保持合法。否则即使测试通过，也可能是因为缺少其他字段，不能证明目标字段真的被拒绝。

## 项目中的边界示例

- 订单金额允许 `0`：可能存在赠品或零元订单，所以使用大于或等于 0。
- 退款金额必须大于 `0`：没有资金退回时，不应形成一条退款资金记录。
- `max_rows` 默认 100，最少 1，最多 1000：防止一次查询返回过多数据。

这些是当前项目制定的业务规则，不是 Pydantic 天生知道的规则。规则变化时，模型和测试都要同步评估。

## 自测

### 1. 是谁拦截负数，又是谁判断“拦截行为正确”？

<details>
<summary>展开标准答案</summary>

Pydantic 根据模型规则拦截负数并抛出 `ValidationError`；pytest 运行测试并检查是否收到了预期错误。

</details>

### 2. `with pytest.raises(ValidationError)` 是否会主动制造错误？

<details>
<summary>展开标准答案</summary>

不会。它只声明期待收到这种错误。真正的错误由代码中的 Pydantic 校验产生；如果没有产生，pytest 会判定测试失败。

</details>

### 3. 为什么测试 `max_rows=1001` 时，其他字段必须合法？

<details>
<summary>展开标准答案</summary>

这样才能把失败原因隔离到 `max_rows`。如果其他必填字段缺失或非法，即使模型创建失败，也不能证明 `max_rows=1001` 被正确拒绝。

</details>

### 4. `Decimal` 为什么不是从 `python` 导入？

<details>
<summary>展开标准答案</summary>

Python 是语言和运行时，不是一个包含所有功能的名为 `python` 的模块。`Decimal` 定义在标准库的 `decimal` 模块中，所以写 `from decimal import Decimal`。

</details>

## 1 分钟口述

用“规则执行者、错误、测试观察者、回归保护”四个词，说明 Pydantic 与 pytest 的职责区别。
