# 卡片 04：FastAPI、HTTP 与接口测试

## 接口函数是什么

Pydantic 的 `AnalysisRequest` 是数据模型类，不是接口函数。接口函数是被 FastAPI 路由装饰器标记、在收到请求后执行的 Python 函数，例如：

```python
@app.post("/analysis/validate")
def validate_analysis(request: AnalysisRequest):
    return request
```

这里发生了四件事：

1. FastAPI 根据路径和请求方法匹配路由。
2. FastAPI 解析客户端发来的 JSON。
3. Pydantic 用 `AnalysisRequest` 校验并转换数据。
4. 校验成功才调用 `validate_analysis` 接口函数。

这就是“定义路由和解析请求”的核心含义。

## GET 与 POST

- `GET` 通常读取资源或状态，一般不用于创建业务数据。
- `POST` 通常把请求体提交给服务端，用于创建资源或触发一次处理。

当前项目：

- `GET /health` 检查应用是否存活，成功返回 HTTP 200 和 `{"status": "ok"}`。
- `POST /analysis/validate` 接收分析请求，成功返回 HTTP 200 和校验后的请求字段。

## 200 与 422

- `200 OK`：请求已被接口成功处理。它不代表业务系统的所有功能都正确，只代表这一次请求成功。
- `422 Unprocessable Content`：JSON 格式能够解析，但字段不满足 Pydantic 规则，例如 `max_rows=1001` 超过上限。

422 响应中的 `detail`、错误位置和英文提示由 FastAPI/Pydantic 根据校验错误结构化生成，不是开发者逐字手写的。

## TestClient 为什么不启动 Uvicorn 也能测试

TestClient 在 pytest 进程内通过 ASGI 直接调用 FastAPI 应用：

```text
测试代码 -> TestClient -> FastAPI 路由 -> Pydantic -> 接口函数 -> JSON 响应
```

它可以验证路由、请求解析、模型校验、接口函数和响应内容，但不能验证：

- Uvicorn 是否正确监听真实端口。
- TCP、代理、HTTPS 和网络波动。
- Docker 或生产部署配置。
- 尚未接入的外部数据库与大模型服务。

## 为什么模型测试和接口测试都要有

虽然接口使用同一个 `AnalysisRequest`，两类测试验证的是不同合同：

- 模型测试：直接创建模型，证明模型规则与默认值正确。
- 接口测试：证明指定路由确实使用这个模型，并把状态码和 JSON 正确返回给客户端。

客户端可以是浏览器前端、手机应用、其他后端服务或测试程序，不只等于前端页面。

## 自测

### 1. 非法 JSON 字段为什么不会进入接口函数？

<details>
<summary>展开标准答案</summary>

FastAPI 在调用接口函数前先用 `AnalysisRequest` 解析和校验请求。校验失败时直接生成 422 响应，接口函数不会执行。

</details>

### 2. TestClient 能证明真实网络部署没问题吗？

<details>
<summary>展开标准答案</summary>

不能。它在测试进程内通过 ASGI 调用应用，不经过真实端口、TCP、代理和 HTTPS。真实网络与部署还需要启动 Uvicorn 或进入部署环境后另行验证。

</details>

### 3. `max_rows=1000` 与 `max_rows=1001` 分别是什么结果？

<details>
<summary>展开标准答案</summary>

当前规则是小于或等于 1000，所以 1000 合法并返回 200；1001 超过上限，Pydantic 校验失败，FastAPI 返回 422，接口函数不执行。

</details>

### 4. 为什么模型测试通过，不代表路由一定正确？

<details>
<summary>展开标准答案</summary>

模型测试没有验证请求方法、路径、FastAPI 是否使用了该模型、HTTP 状态码和 JSON 响应。路由可能绑定错误或返回合同错误，因此仍需接口测试。

</details>

## 1 分钟口述

从“一次 POST JSON 到达系统”开始，依次说明 FastAPI、Pydantic、接口函数和 TestClient 的职责与边界。
