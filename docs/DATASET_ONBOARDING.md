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

当前导入器生成一个规范化的 `dataset_rows` 表，SchemaProfiler 提供候选字段角色而不是最终业务语义。管理员确认指标口径和字段映射后，后续任务才会把 `SchemaProfile` 接入 Agent 的指标语义层。暂不支持 MySQL 直连、任意多表关系自动推断或生产级异步大文件队列。
