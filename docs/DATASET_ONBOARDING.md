# 销售数据接入

知枢 Nexus 当前支持把符合接入契约的销售 CSV 或 Parquet 文件导入独立的 PostgreSQL staging schema。这个流程解决的是“数据集换了以后，Agent 仍然复用同一套分析工作流”，不是承诺对任意文件零配置分析。

## 接入契约

- `dataset_id` 只允许小写字母、数字和下划线，长度不超过 60。
- 每个数据集使用递增的 `version`，同一 `(dataset_id, version)` 只登记一次。
- CSV/Parquet 的列名会转成小写 snake_case；规范化后重名会拒绝。
- 文件中的金额、整数、布尔值和 ISO 时间会做基础类型推断；空值保留为 `NULL`。
- 原始文件必须位于 `DATASET_UPLOAD_ROOT` 下，服务端不会把客户端文件名当作 SQL 标识符。
- 质量检查通过后仍需要管理员确认指标和字段映射，数据集才会进入 `ready`。

## 状态流转

```text
uploaded -> profiling -> needs_mapping -> ready
                 \-> failed
ready -> archived
```

每个文件版本会进入 `staging_<dataset_id>_<version>.dataset_rows`。原有 `public.orders` 等演示表不受影响，Agent 查询仍然必须经过既有的只读 SQL 安全路径。

## 管理员 API

### 1. 注册文件

需要管理员身份的 multipart 请求：

```text
POST /admin/datasets
dataset_id=demo_sales
dataset_name=Demo sales
version=1
source_type=csv
file=<orders.csv>
```

注册只保存文件和元数据，状态为 `uploaded`。服务端将文件保存为类似 `demo_sales/v1.csv` 的受控路径。

### 2. 导入并探查

```text
POST /admin/datasets/demo_sales/profile?version=1
```

接口会依次执行 staging 导入、SchemaProfile 探查和 QualityReport 检查。质量不通过时返回报告并把版本标记为 `failed`；通过时标记为 `needs_mapping`，不会自动变成可查询数据集。

对已经分析过的数据集（`needs_mapping`/`ready`/`failed`/`archived`）重复调用是幂等的：只重新读取 SchemaProfile，不会重复导入、不改变状态，管理员界面因此可以反复查看详情。

### 3. 确认字段和指标映射

探查响应会返回确定性生成的映射草稿。管理员可以编辑后提交：

```json
POST /admin/datasets/demo_sales/mapping?version=1
{
  "dataset_id": "demo_sales",
  "version": 1,
  "mapping_version": "v1",
  "fields": [
    {
      "role": "amount",
      "table": "dataset_rows",
      "column": "total_amount",
      "confidence": 0.95,
      "reasons": ["管理员确认销售金额字段"]
    }
  ],
  "confirmed": false
}
```

服务端会再次读取当前 SchemaProfile，校验表、字段和基础类型兼容性，随后才保存 `mapping_confirmed=true`。

### 4. 启用数据集

```json
POST /admin/datasets/demo_sales/ready?version=1
{
  "mapping_confirmed": true
}
```

只有质量报告通过且注册表中存在已校验的确认映射，才能进入 `ready`。管理员可以通过 `GET /admin/datasets` 查看未归档数据集。

### 5. 指标建议与确认

映射确认后，为当前数据集自动生成版本化指标建议：

```text
POST /admin/datasets/demo_sales/metrics/proposals?version=1
```

返回按语义角色推导的指标（销售额、订单数、销量、平均订单金额等），每条为 `proposed` 状态。管理员逐条确认：

```json
POST /admin/datasets/demo_sales/metrics/confirm?version=1
{
  "metric_id": "sales_amount"
}
```

确认后的指标状态变为 `confirmed`，才能被分析员查询使用；`ready` 数据集至少需要一个可查询指标。指标版本不可静默覆盖，新定义创建新版本。

### 6. 归档

```text
POST /admin/datasets/demo_sales/archive?version=1
```

只允许从 `ready` 或 `failed` 归档。归档后该数据集不再出现在 `GET /datasets` 分析员视图中。

### 7. 界面入口

以上全部能力都有对应页面，不需要手写 API：

- 管理员：「数据集管理」页完成上传 → 数据画像 → 字段映射确认 → 指标确认 → 标记 `ready`/`archived`，质量问题和缺失字段原因直接展示在界面上。
- 分析员：分析工作台顶部「数据范围」下拉选择某个就绪数据集，Agent 只基于该数据集的 Schema 与已确认指标生成和校验 SQL；回答与执行记录会标注数据集版本与指标口径。

## 本地复现

安装基础开发依赖即可运行现有 API 和 CSV 测试：

```powershell
python -m pip install -e ".[dev]"
python -m pytest tests/test_dataset_models.py tests/test_dataset_registry.py tests/test_data_import.py tests/test_schema_profiler.py tests/test_dataset_api.py -q
```

需要 Parquet 时安装可选依赖：

```powershell
python -m pip install -e ".[data]"
```

完整 PostgreSQL 验证仍需使用项目的 Compose 数据库和迁移命令。上传根目录通过 `DATASET_UPLOAD_ROOT` 配置，必须是绝对路径；默认目录为应用当前目录下的 `data/uploads`。

## 当前边界

当前导入器生成一个规范化的 `dataset_rows` 表，SchemaProfiler 提供候选字段角色而不是最终业务语义；字段映射和指标口径必须由管理员确认，模型建议不能直接生效。退款率、复购率等需要额外状态字段或客户口径的指标，字段不足时不会自动发布。暂不支持 MySQL 直连、任意多表关系自动推断、生产级异步大文件队列或租户级权限隔离。Agent 每次分析只能访问当前选中的就绪数据集，不允许跨数据集 JOIN。
