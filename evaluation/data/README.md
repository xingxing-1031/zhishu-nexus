# 跨数据集评测数据

本目录存放阶段5（跨数据集真实评测）的第二套销售数据集。

## 数据集：cross_dataset_sales

| 项 | 值 |
|---|---|
| 文件 | `cross_dataset_sales.csv` |
| 快照 SHA-256 | `c675d94c1634f28d7b6c4858e2db9a38a029c0c0548a79d73157aa2d9b1bc0b2` |
| 行数 | 1000 |
| 日期范围 | 2025-01-01 ~ 2025-12-31（UTC） |
| 来源 | **受控合成数据**，非真实业务数据，不含任何个人或敏感信息 |
| 生成方式 | `scripts/build_cross_dataset_data.py`，固定 seed `20260826`，可复现 |
| 许可 | 仅用于本仓库评测与演示；数据本身无版权主张，可自由使用 |

## 与固定 demo 表的差异（迁移契约的验证点）

固定 demo 表（`orders` / `order_items` / `refunds`）为公共库表，列名与分布如下；第二套数据刻意在多个维度上不同，以证明分析链路与接入契约不依赖固定表：

| 维度 | 固定 demo | cross_dataset_sales |
|---|---|---|
| 表/模式 | 公共库多表 join | 单 staging 表 `dataset_rows` |
| 订单列 | `order_id` | `order_no` |
| 商品列 | `product_id` | `sku` |
| 金额列 | `sales_amount` | `gross_amount` |
| 数量列 | `quantity` | `qty` |
| 渠道列 | `channel`（app/web/store） | `source`（e_commerce/retail_store/catalog） |
| 区域列 | 无区域维度 | `region_code`（north/south/east/west） |
| 品类列 | `category` | `product_category` |
| 日期列 | `created_at` | `sale_date` |
| 日期范围 | 2026 附近 | 2025 全年 |
| 缺失情况 | 较少 | `region_code` 约 3% 缺失、`cost_amount` 约 9% 缺失 |

## 列说明

| 列 | 类型推断 | 语义 | 映射角色 |
|---|---|---|---|
| `order_no` | text | 唯一订单号 | `order_id` |
| `sku` | text | 商品编码 | `product_id` |
| `product_name` | text | 商品名 | — |
| `product_category` | text | 品类（electronics/apparel/home） | `category` |
| `source` | text | 销售渠道 | `channel` |
| `region_code` | text | 销售区域 | `region` |
| `qty` | integer | 数量 | `quantity` |
| `gross_amount` | numeric | 成交金额 | `amount` |
| `cost_amount` | numeric | 成本（约 9% 缺失） | — |
| `sale_date` | timestamptz | 交易时间 | `time` |

## 已知边界

- 列名特意避开含 `sales`/`amount`/`total` 的维度列（如 `sales_region`）：现有
  `propose_mapping` 的 `amount` 同义词含 `sales`，会把 `sales_region` 误判为金额列。
  本数据集用 `region_code` 规避该歧义；该边界已在阶段5报告中记录，不在本阶段修改
  核心映射逻辑。
- 指标自动建议只生成确定可证的四个（`sales_amount` / `avg_order_value` /
  `order_count` / `units_sold`），不包含退款率等需要额外状态与定义的指标。
