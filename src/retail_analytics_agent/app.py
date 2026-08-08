import asyncio
import logging
from pathlib import Path
from queue import Queue
from threading import Thread
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from retail_analytics_agent.access_control import get_access_context
from retail_analytics_agent.auth import (
    SESSION_COOKIE,
    issue_session,
    verify_password,
)
from retail_analytics_agent.analysis_service import (
    AnalysisRequestConflictError,
    AnalysisRunError,
    AnalysisRunner,
    get_analysis_runner,
)
from retail_analytics_agent.database import (
    DatabaseConnection,
    check_database_readiness,
    close_database_pool,
    get_database_connection,
)
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisRequest,
    AnalysisOutcome,
    AnalysisResponse,
    AnalysisRunningResponse,
    AnalysisStreamEvent,
    ApprovalRequiredResponse,
    ApprovalResolutionRequest,
    ChannelSalesSummary,
    OrderStatusSummary,
    ProductSalesSummary,
    RefundStatusSummary,
    SessionInfo,
)
from retail_analytics_agent.model_adapters import ModelInvocationError
from retail_analytics_agent.public_errors import public_error_message
from retail_analytics_agent.observability import configure_logging
from retail_analytics_agent.queries import (
    get_channel_sales_summary,
    get_order_status_summary,
    get_product_sales_summary,
    get_refund_status_summary,
)
from retail_analytics_agent.rate_limit import SlidingWindowRateLimiter
from retail_analytics_agent.settings import Settings, get_settings
from retail_analytics_agent.tracing import ExecutionTraceResponse


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    try:
        yield
    finally:
        close_database_pool()


app = FastAPI(
    title="零售运营可审计分析助手",
    version="0.1.0",
    lifespan=lifespan,
)
_STATIC_DIR = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
analysis_rate_limiter = SlidingWindowRateLimiter()
login_rate_limiter = SlidingWindowRateLimiter()


@app.middleware("http")
async def record_request(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.exception(
            "request failed",
            extra={
                "event": "http_request_error",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "duration_ms": round((perf_counter() - started) * 1000),
                "client_host": request.client.host if request.client else "unknown",
                "error_type": type(exc).__name__,
            },
        )
        raise
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request completed",
        extra={
            "event": "http_request",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((perf_counter() - started) * 1000),
            "client_host": request.client.host if request.client else "unknown",
        },
    )
    return response


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


def _enforce_public_demo_request(
    http_request: Request,
    analysis_request: AnalysisRequest,
    settings: Settings,
) -> None:
    if not settings.public_demo_mode:
        return
    if analysis_request.max_rows > settings.public_demo_max_rows:
        raise HTTPException(
            status_code=422,
            detail=(
                "公开演示环境单次最多返回 "
                f"{settings.public_demo_max_rows} 行数据。"
            ),
        )
    client_host = (
        http_request.client.host
        if http_request.client is not None
        else "unknown"
    )
    retry_after = analysis_rate_limiter.consume(
        client_host,
        limit=settings.public_demo_rate_limit_per_minute,
        window_seconds=60,
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="请求过于频繁，请稍后再试。",
            headers={"Retry-After": str(retry_after)},
        )


def _reject_public_internal_endpoint(settings: Settings) -> None:
    if settings.public_demo_mode:
        raise HTTPException(
            status_code=403,
            detail="公开演示环境不提供内部执行接口。",
        )


@app.get("/", include_in_schema=False)
def read_demo() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionInfo:
    if settings.auth_mode != "password":
        raise HTTPException(status_code=404, detail="当前部署使用公开演示身份。")
    client_host = request.client.host if request.client is not None else "unknown"
    retry_after = login_rate_limiter.consume(
        client_host,
        limit=5,
        window_seconds=60,
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="登录尝试过于频繁，请稍后再试。",
            headers={"Retry-After": str(retry_after)},
        )
    if payload.username != settings.auth_username or not settings.auth_password_hash:
        raise HTTPException(status_code=401, detail="用户名或密码错误。")
    if not verify_password(payload.password, settings.auth_password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误。")
    assert settings.auth_session_secret is not None
    token = issue_session(
        user_id=settings.auth_user_id,
        role=settings.auth_role,
        secret=settings.auth_session_secret.get_secret_value(),
        ttl_seconds=settings.auth_session_ttl_seconds,
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.auth_session_ttl_seconds,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
    )
    return SessionInfo(
        user_id=settings.auth_user_id,
        role=settings.auth_role,
        public_demo_mode=False,
        trace_visible=True,
        max_rows=100,
    )


@app.post("/auth/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


@app.get("/ready")
def readiness_check() -> dict[str, str]:
    if not check_database_readiness():
        raise HTTPException(
            status_code=503,
            detail="数据库和业务数据尚未就绪，请稍后重试。",
        )
    return {"status": "ready"}


@app.get("/demo/overview")
def read_demo_overview(
    _access_context: Annotated[
        AccessContext,
        Depends(get_access_context),
    ],
    connection: Annotated[
        DatabaseConnection,
        Depends(get_database_connection),
    ],
) -> dict[str, int]:
    row = connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM orders) AS order_count,
            (SELECT COUNT(*) FROM products) AS product_count,
            (SELECT COUNT(*) FROM refunds) AS refund_count,
            (SELECT COUNT(DISTINCT channel) FROM orders) AS channel_count,
            COALESCE(
                EXTRACT(DAY FROM MAX(created_at) - MIN(created_at)),
                0
            )::INTEGER AS coverage_days
        FROM orders
        """
    ).fetchone()
    assert row is not None
    return {key: int(value) for key, value in row.items()}


@app.get("/session", response_model=SessionInfo)
def read_session(
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionInfo:
    return SessionInfo(
        user_id=access_context.user_id,
        role=access_context.role,
        public_demo_mode=settings.public_demo_mode,
        trace_visible=not settings.public_demo_mode,
        max_rows=(settings.public_demo_max_rows if settings.public_demo_mode else 100),
    )


@app.post("/analysis/validate")
def validate_analysis_request(
    request: AnalysisRequest,
    _access_context: Annotated[
        AccessContext,
        Depends(get_access_context),
    ],
) -> AnalysisRequest:
    return request


@app.post("/analysis/run", response_model=AnalysisOutcome)
def run_analysis(
    analysis_request: AnalysisRequest,
    http_request: Request,
    response: Response,
    runner: Annotated[AnalysisRunner, Depends(get_analysis_runner)],
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnalysisOutcome:
    if analysis_request.user_id != access_context.user_id:
        raise HTTPException(
            status_code=403,
            detail="当前登录身份与请求用户不一致。",
        )
    _enforce_public_demo_request(http_request, analysis_request, settings)
    try:
        result = runner.run(analysis_request, access_context)
        if isinstance(
            result,
            (ApprovalRequiredResponse, AnalysisRunningResponse),
        ):
            response.status_code = 202
        return result
    except AnalysisRequestConflictError as exc:
        raise HTTPException(status_code=409, detail=public_error_message(exc)) from exc
    except ModelInvocationError as exc:
        raise HTTPException(status_code=502, detail=public_error_message(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=public_error_message(exc)) from exc
    except AnalysisRunError as exc:
        raise HTTPException(status_code=500, detail=public_error_message(exc)) from exc


@app.post(
    "/analysis/{request_id}/approval",
    response_model=AnalysisOutcome,
)
def resolve_analysis_approval(
    request_id: str,
    resolution: ApprovalResolutionRequest,
    runner: Annotated[AnalysisRunner, Depends(get_analysis_runner)],
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnalysisOutcome:
    _reject_public_internal_endpoint(settings)
    if access_context.role is not AccessRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="只有管理员可以处理人工审批。",
        )
    try:
        return runner.resume_approval(
            request_id,
            resolution,
            access_context,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="当前身份无权处理这个请求。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=public_error_message(exc)) from exc


@app.get(
    "/analysis/{request_id}",
    response_model=AnalysisOutcome,
)
def read_analysis_status(
    request_id: str,
    runner: Annotated[AnalysisRunner, Depends(get_analysis_runner)],
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnalysisOutcome:
    _reject_public_internal_endpoint(settings)
    try:
        return runner.get_status(request_id, access_context)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="当前身份无权查看这个请求。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="没有找到对应的分析请求。") from exc


@app.get(
    "/analysis/{request_id}/trace",
    response_model=ExecutionTraceResponse,
)
def read_analysis_trace(
    request_id: str,
    runner: Annotated[AnalysisRunner, Depends(get_analysis_runner)],
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ExecutionTraceResponse:
    _reject_public_internal_endpoint(settings)
    try:
        return runner.get_trace(request_id, access_context)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="当前身份无权查看这个执行记录。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="没有找到对应的执行记录。") from exc


_STREAM_DONE = object()


async def _encode_analysis_events(
    runner: AnalysisRunner,
    request: AnalysisRequest,
    access_context: AccessContext,
):
    events: Queue[AnalysisStreamEvent | BaseException | object] = Queue()

    def produce_events() -> None:
        try:
            for event in runner.stream(request, access_context):
                events.put(event)
        except BaseException as exc:
            events.put(exc)
        finally:
            events.put(_STREAM_DONE)

    worker = Thread(
        target=produce_events,
        name=f"analysis-stream-{request.request_id}",
        daemon=True,
    )
    worker.start()

    while True:
        item = await asyncio.to_thread(events.get)
        if item is _STREAM_DONE:
            break
        if isinstance(item, BaseException):
            event = AnalysisStreamEvent(
                event="error",
                message=public_error_message(item),
            )
        else:
            event = item
        yield (
            f"event: {event.event.value}\n"
            f"data: {event.model_dump_json()}\n\n"
        )


@app.post("/analysis/stream")
def stream_analysis(
    analysis_request: AnalysisRequest,
    http_request: Request,
    runner: Annotated[AnalysisRunner, Depends(get_analysis_runner)],
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    if analysis_request.user_id != access_context.user_id:
        raise HTTPException(
            status_code=403,
            detail="当前登录身份与请求用户不一致。",
        )
    _enforce_public_demo_request(http_request, analysis_request, settings)
    return StreamingResponse(
        _encode_analysis_events(runner, analysis_request, access_context),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get(
    "/analytics/channels",
    response_model=list[ChannelSalesSummary],
)
def read_channel_sales_summary(
    _access_context: Annotated[
        AccessContext,
        Depends(get_access_context),
    ],
    connection: Annotated[
        DatabaseConnection,
        Depends(get_database_connection),
    ],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> list[ChannelSalesSummary]:
    return get_channel_sales_summary(connection, days=days)


@app.get(
    "/analytics/products",
    response_model=list[ProductSalesSummary],
)
def read_product_sales_summary(
    _access_context: Annotated[
        AccessContext,
        Depends(get_access_context),
    ],
    connection: Annotated[
        DatabaseConnection,
        Depends(get_database_connection),
    ],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> list[ProductSalesSummary]:
    return get_product_sales_summary(
        connection,
        days=days,
        limit=limit,
    )


@app.get(
    "/analytics/refunds/statuses",
    response_model=list[RefundStatusSummary],
)
def read_refund_status_summary(
    _access_context: Annotated[
        AccessContext,
        Depends(get_access_context),
    ],
    connection: Annotated[
        DatabaseConnection,
        Depends(get_database_connection),
    ],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> list[RefundStatusSummary]:
    return get_refund_status_summary(connection, days=days)


@app.get(
    "/analytics/orders/statuses",
    response_model=list[OrderStatusSummary],
)
def read_order_status_summary(
    _access_context: Annotated[
        AccessContext,
        Depends(get_access_context),
    ],
    connection: Annotated[
        DatabaseConnection,
        Depends(get_database_connection),
    ],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> list[OrderStatusSummary]:
    return get_order_status_summary(connection, days=days)
