# Retail Analytics Agent

面向零售运营的可审计数据分析 Agent，也是 2026 秋招的主项目。

## 当前状态

- 当前任务：`W1-1` 项目初始化
- 总进度：`0 / 32`
- 进度明细：查看 [../PROGRESS.md](../PROGRESS.md)
- 可视化面板：直接打开 `../progress.html`
- 学习记录：查看 [../LEARNING_LOG.md](../LEARNING_LOG.md)
- 项目升级清单：查看 [docs/UPGRADE_BACKLOG.md](docs/UPGRADE_BACKLOG.md)

## 本周目标

完成 Python 项目结构、领域模型、基础测试、数据库设计和 FastAPI 查询接口。

## 本地初始化

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest
```

## 目录结构

```text
retail-analytics-agent/
|-- src/retail_analytics_agent/   # 项目源码
|-- tests/                        # 自动化测试
|-- docs/                         # 架构、学习材料和评测文档
|-- pyproject.toml
`-- README.md
```

## 完成定义

一个里程碑只有同时满足以下条件才能标记完成：

1. 功能代码已经提交。
2. 自动化测试通过。
3. 能够脱离代码解释设计与原理。
4. 上级目录的 `PROGRESS.md` 中记录了验收证据。
