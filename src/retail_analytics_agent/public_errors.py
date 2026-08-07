from __future__ import annotations

"""Convert internal failures to stable, user-facing Chinese messages.

Detailed exception text remains in the execution trace for authorized diagnosis.
"""


def public_error_message(error: BaseException | str) -> str:
    raw = str(error).strip()
    message = raw.casefold()

    if "already bound" in message or "different analysis input" in message:
        return "这个请求编号已经对应其他问题，请重新发起分析。"
    if "does not support dimensions" in message:
        return "当前指标不支持所选分组维度，请调整指标或分组方式。"
    if "invalid analysis plan" in message or "analysis plan" in message:
        return "当前问题未能形成有效分析计划，请明确指标、维度和时间范围。"
    if "timeout" in message or "timed out" in message or "deadline" in message:
        return "分析服务响应超时，请稍后重试。"
    if "ollama" in message or "model invocation" in message:
        return "分析模型暂时不可用，请稍后重试。"
    if (
        "database" in message
        or "postgres" in message
        or "psycopg" in message
        or "connection" in message
    ):
        return "数据服务暂时不可用，请稍后重试。"
    if (
        "sql" in message
        or "unsafe" in message
        or "business consistency" in message
        or "validation failed" in message
    ):
        return "生成的查询未通过安全或业务校验，系统已停止执行。"
    if "permission" in message or "admin" in message or "forbidden" in message:
        return "当前身份无权执行这个操作。"
    if "not found" in message:
        return "没有找到对应的分析请求。"
    return "分析未能完成，请调整问题后重试。"
