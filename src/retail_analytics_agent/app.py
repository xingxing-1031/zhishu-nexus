import asyncio
import hmac
import logging
import re
import sys
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from queue import Queue
from threading import Thread
from time import perf_counter
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from retail_analytics_agent.access_control import get_access_context
from retail_analytics_agent.admin_views import (
    AdminAuditEntry,
    AdminAuditStatus,
    MetricDefinitionView,
    list_admin_audit_entries,
    list_metric_definitions,
)
from retail_analytics_agent.agent_models import (
    AgentMode,
    AgentRequest,
    AgentResponse,
    AgentStreamEvent,
    AgentTaskStatus,
)
from retail_analytics_agent.agent_runs import DatabaseAgentRunStore
from retail_analytics_agent.agent_service import EnterpriseAgentService
from retail_analytics_agent.analysis_service import (
    AnalysisRequestConflictError,
    AnalysisRunError,
    AnalysisRunner,
    get_analysis_runner,
)
from retail_analytics_agent.auth import (
    SESSION_COOKIE,
    issue_session,
    verify_password,
)
from retail_analytics_agent.context_builder import ContextBuilder
from retail_analytics_agent.context_store import PostgresConversationStore
from retail_analytics_agent.data_import import (
    FileDatasetImporter,
    ImportRequest,
    ImportResult,
    get_dataset_importer,
)
from retail_analytics_agent.database import (
    DatabaseConnection,
    check_database_readiness,
    close_database_pool,
    connect_to_database,
    get_database_connection,
)
from retail_analytics_agent.dataset_mapping import (
    DatasetMapping,
    MappingValidationError,
    propose_mapping,
    validate_mapping,
)
from retail_analytics_agent.dataset_models import (
    DatasetRecord,
    DatasetSourceType,
    DatasetStatus,
    QualityReport,
    SchemaProfile,
)
from retail_analytics_agent.dataset_registry import (
    DatasetRegistry,
    DatasetRegistryError,
    get_dataset_registry,
)
from retail_analytics_agent.general_agent import GeneralAgent
from retail_analytics_agent.knowledge_adapter import HttpKnowledgeAdapter
from retail_analytics_agent.mcp_client import McpToolClient
from retail_analytics_agent.model_adapters import ModelInvocationError
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisOutcome,
    AnalysisRequest,
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
from retail_analytics_agent.observability import configure_logging
from retail_analytics_agent.public_errors import public_error_message
from retail_analytics_agent.queries import (
    get_channel_sales_summary,
    get_order_status_summary,
    get_product_sales_summary,
    get_refund_status_summary,
)
from retail_analytics_agent.rate_limit import SlidingWindowRateLimiter
from retail_analytics_agent.schema_profiler import (
    SchemaProfiler,
    SchemaProfilerError,
    get_schema_profiler,
)
from retail_analytics_agent.settings import Settings, get_settings
from retail_analytics_agent.skills import default_skill_registry
from retail_analytics_agent.structured_chat import StructuredChatClient
from retail_analytics_agent.supervisor import Supervisor
from retail_analytics_agent.task_planner import TaskPlanner
from retail_analytics_agent.tracing import ExecutionTraceResponse
from retail_analytics_agent.workspace_history import (
    PostgresWorkspaceHistoryStore,
    WorkspaceConversationPayload,
    WorkspaceHistoryStore,
)
from retail_analytics_agent.zhishu_service import (
    AgentRunConflictError,
    StructuredEvidenceAnswerer,
    ZhishuAgentService,
)

logger = logging.getLogger(__name__)


def _mcp_server_path() -> Path | None:
    """Locate the bundled MCP server in source and installed-container layouts."""
    candidates = (
        Path(__file__).resolve().parents[2] / "mcp_server" / "operations_export_server.py",
        Path.cwd() / "mcp_server" / "operations_export_server.py",
        Path("/app/mcp_server/operations_export_server.py"),
    )
    return next((path for path in candidates if path.is_file()), None)


def _common_mcp_server_path() -> Path | None:
    candidates = (
        Path(__file__).resolve().parents[2] / "mcp_server" / "common_tools_server.py",
        Path.cwd() / "mcp_server" / "common_tools_server.py",
        Path("/app/mcp_server/common_tools_server.py"),
    )
    return next((path for path in candidates if path.is_file()), None)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    try:
        yield
    finally:
        close_database_pool()


app = FastAPI(
    title="知枢 Nexus 企业智能 Agent 平台",
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


class InternalAgentRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=40)
    departments: list[str] = Field(default_factory=list, max_length=20)
    question: str = Field(min_length=1, max_length=4000)
    as_of: str | None = None


class InternalAgentResult(BaseModel):
    status: str
    skill_id: str | None = None
    answer: str = ""
    rows: list[dict] = Field(default_factory=list)
    chart: dict | None = None
    report: dict | None = None
    tool_calls: list[dict] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class DatasetReadyRequest(BaseModel):
    mapping_confirmed: bool


class DatasetProfileResponse(BaseModel):
    model_config = {"populate_by_name": True}

    dataset: DatasetRecord
    import_result: ImportResult
    schema_: SchemaProfile = Field(alias="schema")
    mapping: DatasetMapping
    quality: QualityReport


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
    if settings.public_demo_mode and settings.auth_mode != "password":
        raise HTTPException(
            status_code=403,
            detail="公开演示环境不提供内部执行接口。",
        )


def _require_admin_access(
    access_context: AccessContext,
    settings: Settings,
) -> None:
    _reject_public_internal_endpoint(settings)
    if access_context.role is not AccessRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="只有管理员可以查看这个页面。",
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
    accounts = [
        (
            settings.auth_username,
            settings.auth_user_id,
            settings.auth_role,
            settings.auth_password_hash,
        ),
        (
            settings.auth_admin_username,
            settings.auth_admin_user_id,
            AccessRole.ADMIN,
            settings.auth_admin_password_hash,
        ),
    ]
    account = next(
        (
            item
            for item in accounts
            if item[0] == payload.username
            and item[3]
            and verify_password(payload.password, item[3])
        ),
        None,
    )
    if account is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误。")
    _, user_id, role, _ = account
    assert settings.auth_session_secret is not None
    token = issue_session(
        user_id=user_id,
        role=role,
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
        user_id=user_id,
        role=role,
        public_demo_mode=settings.public_demo_mode,
        trace_visible=True,
        max_rows=(settings.public_demo_max_rows if settings.public_demo_mode else 100),
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
        trace_visible=(not settings.public_demo_mode or settings.auth_mode == "password"),
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


def get_workspace_history_store() -> WorkspaceHistoryStore:
    return PostgresWorkspaceHistoryStore(connect_to_database)


@app.get(
    "/agent/conversations",
    response_model=list[WorkspaceConversationPayload],
)
def list_workspace_conversations(
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    store: Annotated[
        WorkspaceHistoryStore,
        Depends(get_workspace_history_store),
    ],
) -> tuple[WorkspaceConversationPayload, ...]:
    return store.list_for_user(access_context.user_id)


@app.put(
    "/agent/conversations/{conversation_id}",
    response_model=WorkspaceConversationPayload,
)
def save_workspace_conversation(
    conversation_id: str,
    payload: WorkspaceConversationPayload,
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    store: Annotated[
        WorkspaceHistoryStore,
        Depends(get_workspace_history_store),
    ],
) -> WorkspaceConversationPayload:
    if payload.id != conversation_id:
        raise HTTPException(status_code=422, detail="会话 ID 与请求路径不一致。")
    return store.put(access_context.user_id, payload)


@app.delete(
    "/agent/conversations/{conversation_id}",
    status_code=204,
)
def delete_workspace_conversation(
    conversation_id: str,
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    store: Annotated[
        WorkspaceHistoryStore,
        Depends(get_workspace_history_store),
    ],
) -> None:
    store.delete(access_context.user_id, conversation_id)


def get_agent_service(
    runner: Annotated[AnalysisRunner, Depends(get_analysis_runner)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[ZhishuAgentService]:
    knowledge = None
    client = None
    model_client = None
    mcp_client = None
    common_mcp_client = None
    if settings.knowledge_service_url:
        client = httpx.Client(timeout=settings.model_timeout_seconds or 30)
        assert settings.knowledge_service_token is not None
        knowledge = HttpKnowledgeAdapter(
            settings.knowledge_service_url,
            client,
            timeout_seconds=settings.model_timeout_seconds or 30,
            service_token=settings.knowledge_service_token.get_secret_value(),
        )
    if settings.mcp_export_enabled:
        mcp_server = _mcp_server_path()
        if mcp_server is None:
            logger.warning("MCP export server file is unavailable; export disabled")
        else:
            mcp_client = McpToolClient(
                command=sys.executable,
                args=(str(mcp_server),),
                timeout_seconds=settings.mcp_export_timeout_seconds,
            )
    if settings.mcp_common_enabled:
        common_server = _common_mcp_server_path()
        if common_server is None:
            logger.warning("Common MCP server file is unavailable; common tools disabled")
        else:
            common_mcp_client = McpToolClient(
                command=sys.executable,
                args=(str(common_server),),
                timeout_seconds=settings.mcp_common_timeout_seconds,
            )
    model_client = httpx.Client(
        base_url=settings.active_model_base_url,
        headers=settings.model_client_headers,
        timeout=settings.active_model_timeout_seconds,
    )
    try:
        data_agent = EnterpriseAgentService(
            analysis_runner=runner,
            context_builder=ContextBuilder(
                PostgresConversationStore(connect_to_database)
            ),
            task_planner=TaskPlanner(
                default_skill_registry(),
                default_max_steps=settings.agent_max_steps,
            ),
            knowledge=knowledge,
            knowledge_departments=settings.active_knowledge_departments,
            max_context_token_budget=settings.agent_context_token_budget,
            mcp_client=mcp_client,
        )
        model = StructuredChatClient(model_client, settings.model_provider)
        yield ZhishuAgentService(
            data_agent=data_agent,
            supervisor=Supervisor(),
            general_agent=GeneralAgent(
                model=model,
                mcp_client=common_mcp_client,
                model_name=settings.active_model_name,
                timeout_seconds=settings.active_model_timeout_seconds,
                max_tool_calls=min(settings.agent_max_steps, 3),
            ),
            knowledge=knowledge,
            answerer=StructuredEvidenceAnswerer(
                model,
                model_name=settings.active_model_name,
                timeout_seconds=settings.active_model_timeout_seconds,
            ),
            knowledge_departments=settings.active_knowledge_departments,
            run_store=DatabaseAgentRunStore(),
        )
    finally:
        if client is not None:
            client.close()
        if model_client is not None:
            model_client.close()


@app.post("/agent/run", response_model=AgentResponse)
def run_agent(
    agent_request: AgentRequest,
    http_request: Request,
    service: Annotated[ZhishuAgentService, Depends(get_agent_service)],
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentResponse:
    if agent_request.user_id != access_context.user_id:
        raise HTTPException(
            status_code=403,
            detail="当前登录身份与请求用户不一致。",
        )
    _enforce_public_demo_request(
        http_request,
        AnalysisRequest(
            request_id=agent_request.request_id,
            user_id=agent_request.user_id,
            question=agent_request.question,
            max_rows=agent_request.max_rows,
        ),
        settings,
    )
    try:
        return service.run(agent_request, access_context)
    except AgentRunConflictError as exc:
        raise HTTPException(status_code=409, detail=public_error_message(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="当前身份无权执行该任务。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=public_error_message(exc)) from exc


@app.get("/agent/runs/{request_id}", response_model=AgentResponse)
def get_agent_run(
    request_id: str,
    service: Annotated[ZhishuAgentService, Depends(get_agent_service)],
    access_context: Annotated[AccessContext, Depends(get_access_context)],
) -> AgentResponse:
    try:
        response = service.get_status(request_id, access_context)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="当前身份无权查看该任务。") from exc
    if response is None:
        raise HTTPException(status_code=404, detail="没有找到对应的 Agent 请求。")
    if response.status is AgentTaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Agent 请求仍在执行中。")
    return response


@app.post(
    "/internal/agent",
    response_model=InternalAgentResult,
    include_in_schema=False,
)
def run_internal_agent(
    payload: InternalAgentRequest,
    request: Request,
    service: Annotated[ZhishuAgentService, Depends(get_agent_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InternalAgentResult:
    configured = settings.internal_service_token
    supplied = request.headers.get("X-Internal-Token", "")
    if configured is None or not hmac.compare_digest(
        supplied, configured.get_secret_value()
    ):
        raise HTTPException(status_code=401, detail="内部服务认证失败。")
    role = (
        AccessRole.ADMIN
        if payload.role in {"department_admin", "knowledge_admin", "admin"}
        else AccessRole.ANALYST
    )
    data_service = getattr(service, "data_agent", service)
    response = data_service.run(
        AgentRequest(
            request_id=payload.request_id,
            conversation_id=payload.session_id or payload.request_id,
            user_id=payload.user_id,
            question=payload.question,
            max_rows=settings.public_demo_max_rows,
            include_knowledge=False,
        ),
        AccessContext(user_id=payload.user_id, role=role),
    )
    analysis = response.analysis
    rows = list(getattr(analysis, "rows", []) or [])
    chart_spec = getattr(analysis, "chart_spec", None)
    chart = chart_spec.model_dump(mode="json") if chart_spec is not None else None
    report = response.report.model_dump(mode="json") if response.report else None
    analysis_answer = getattr(analysis, "answer", "")
    answer = (
        analysis_answer
        or (
            response.report.executive_summary
            if response.report is not None
            else ""
        )
    )
    evidence_ids: list[str] = []
    if response.report is not None:
        evidence_ids.extend(response.report.data_evidence)
        evidence_ids.extend(response.report.document_evidence)
    return InternalAgentResult(
        status=response.status.value,
        skill_id=response.skill_id.value if response.skill_id else None,
        answer=answer,
        rows=rows,
        chart=chart,
        report=report,
        tool_calls=[item.model_dump(mode="json") for item in response.tool_calls],
        evidence_ids=list(dict.fromkeys(evidence_ids)),
        limitations=list(response.limitations),
    )


@app.post("/agent/stream")
async def stream_agent(
    agent_request: AgentRequest,
    http_request: Request,
    service: Annotated[ZhishuAgentService, Depends(get_agent_service)],
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    if agent_request.user_id != access_context.user_id:
        raise HTTPException(
            status_code=403,
            detail="当前登录身份与请求用户不一致。",
        )
    _enforce_public_demo_request(
        http_request,
        AnalysisRequest(
            request_id=agent_request.request_id,
            user_id=agent_request.user_id,
            question=agent_request.question,
            max_rows=agent_request.max_rows,
        ),
        settings,
    )

    events: Queue[object] = Queue()

    def produce_events() -> None:
        try:
            for event in service.stream(agent_request, access_context):
                events.put(event)
        except BaseException as exc:
            events.put(exc)
        finally:
            events.put(_STREAM_DONE)

    Thread(
        target=produce_events,
        name=f"agent-stream-{agent_request.request_id}",
        daemon=True,
    ).start()

    async def encode_events():
        while True:
            item = await asyncio.to_thread(events.get)
            if item is _STREAM_DONE:
                break
            if isinstance(item, BaseException):
                event = AgentStreamEvent(
                    event="error",
                    node="agent",
                    message=public_error_message(item),
                )
            else:
                event = item
            yield (
                f"event: {event.event.value}\n"
                f"data: {event.model_dump_json()}\n\n"
            )

    return StreamingResponse(
        encode_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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


_DATASET_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_]{0,59}")


def _dataset_file_suffix(source_type: DatasetSourceType) -> str:
    if source_type is DatasetSourceType.CSV:
        return ".csv"
    if source_type is DatasetSourceType.PARQUET:
        return ".parquet"
    raise HTTPException(
        status_code=422,
        detail="文件接入只支持 CSV 或 Parquet。",
    )


def _validate_dataset_id(dataset_id: str) -> None:
    if _DATASET_ID_PATTERN.fullmatch(dataset_id) is None:
        raise HTTPException(
            status_code=422,
            detail="dataset_id 只能包含小写字母、数字和下划线。",
        )


def _save_dataset_upload(
    upload: UploadFile,
    *,
    settings: Settings,
    dataset_id: str,
    version: int,
    suffix: str,
) -> str:
    root = settings.dataset_upload_root.resolve()
    target_directory = (root / dataset_id).resolve()
    try:
        target_directory.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="上传路径不安全。") from exc
    target_directory.mkdir(parents=True, exist_ok=True)
    target = target_directory / f"v{version}{suffix}"
    total = 0
    try:
        with target.open("wb") as handle:
            while chunk := upload.file.read(1024 * 1024):
                total += len(chunk)
                if total > settings.dataset_max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="上传文件超过大小限制。",
                    )
                handle.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    return f"{dataset_id}/v{version}{suffix}"


@app.post(
    "/admin/datasets",
    response_model=DatasetRecord,
    status_code=201,
)
def register_dataset(
    dataset_id: Annotated[str, Form(min_length=1, max_length=60)],
    dataset_name: Annotated[str, Form(min_length=1, max_length=200)],
    version: Annotated[int, Form(ge=1)],
    source_type: Annotated[DatasetSourceType, Form()],
    upload: Annotated[UploadFile, File(alias="file")],
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[DatasetRegistry, Depends(get_dataset_registry)],
) -> DatasetRecord:
    _require_admin_access(access_context, settings)
    _validate_dataset_id(dataset_id)
    suffix = _dataset_file_suffix(source_type)
    filename = upload.filename or ""
    if Path(filename).suffix.casefold() != suffix:
        raise HTTPException(
            status_code=422,
            detail=f"{source_type.value} 文件必须使用 {suffix} 扩展名。",
        )
    existing = registry.get(dataset_id, version)
    if existing is not None:
        return existing
    source_ref = _save_dataset_upload(
        upload,
        settings=settings,
        dataset_id=dataset_id,
        version=version,
        suffix=suffix,
    )
    record = DatasetRecord(
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        source_type=source_type,
        source_ref=source_ref,
        schema_name=f"staging_{dataset_id}_{version}",
        version=version,
    )
    return registry.create(record)


@app.post(
    "/admin/datasets/{dataset_id}/profile",
    response_model=DatasetProfileResponse,
)
def profile_dataset(
    dataset_id: str,
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[DatasetRegistry, Depends(get_dataset_registry)],
    importer: Annotated[FileDatasetImporter, Depends(get_dataset_importer)],
    profiler: Annotated[SchemaProfiler, Depends(get_schema_profiler)],
    connection: Annotated[DatabaseConnection, Depends(get_database_connection)],
    version: Annotated[int, Query(ge=1)] = 1,
) -> DatasetProfileResponse:
    _require_admin_access(access_context, settings)
    record = registry.get(dataset_id, version)
    if record is None or record.source_ref is None:
        raise HTTPException(status_code=404, detail="数据集版本不存在。")
    try:
        registry.update_status(dataset_id, DatasetStatus.PROFILING, version=version)
        source_path = settings.dataset_upload_root / record.source_ref
        import_result = importer.import_file(
            ImportRequest(
                dataset_id=record.dataset_id,
                version=record.version,
                source_path=source_path,
                source_type=record.source_type,
                target_schema=record.schema_name,
            ),
            connection,
        )
        schema_profile = profiler.inspect(record.schema_name, connection)
        quality = profiler.quality(record.schema_name, connection)
        mapping = propose_mapping(record.dataset_id, record.version, schema_profile)
        mapped_record = registry.save_mapping(mapping, confirmed=False)
        final_status = (
            DatasetStatus.NEEDS_MAPPING
            if quality.passed
            else DatasetStatus.FAILED
        )
        updated = registry.update_status(
            dataset_id,
            final_status,
            version=version,
            quality_report=quality,
        )
    except (ValueError, RuntimeError, SchemaProfilerError) as exc:
        try:
            registry.update_status(
                dataset_id,
                DatasetStatus.FAILED,
                version=version,
            )
        except DatasetRegistryError:
            logger.exception("failed to mark dataset profiling as failed")
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DatasetProfileResponse(
        dataset=updated if updated.mapping is not None else mapped_record,
        import_result=import_result,
        schema_=schema_profile,
        mapping=mapping,
        quality=quality,
    )


@app.post(
    "/admin/datasets/{dataset_id}/mapping",
    response_model=DatasetRecord,
)
def confirm_dataset_mapping(
    dataset_id: str,
    mapping: DatasetMapping,
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[DatasetRegistry, Depends(get_dataset_registry)],
    profiler: Annotated[SchemaProfiler, Depends(get_schema_profiler)],
    connection: Annotated[DatabaseConnection, Depends(get_database_connection)],
    version: Annotated[int, Query(ge=1)] = 1,
) -> DatasetRecord:
    _require_admin_access(access_context, settings)
    if mapping.dataset_id != dataset_id or mapping.version != version:
        raise HTTPException(status_code=422, detail="映射与数据集版本不一致。")
    record = registry.get(dataset_id, version)
    if record is None:
        raise HTTPException(status_code=404, detail="数据集版本不存在。")
    try:
        profile = profiler.inspect(record.schema_name, connection)
        validated = validate_mapping(mapping, profile)
    except MappingValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return registry.save_mapping(validated, confirmed=True)


@app.post(
    "/admin/datasets/{dataset_id}/ready",
    response_model=DatasetRecord,
)
def mark_dataset_ready(
    dataset_id: str,
    payload: DatasetReadyRequest,
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[DatasetRegistry, Depends(get_dataset_registry)],
    version: Annotated[int, Query(ge=1)] = 1,
) -> DatasetRecord:
    _require_admin_access(access_context, settings)
    if not payload.mapping_confirmed:
        raise HTTPException(status_code=422, detail="请先确认字段指标映射。")
    record = registry.get(dataset_id, version)
    if record is None or record.quality_report is None:
        raise HTTPException(status_code=409, detail="数据集尚未完成质量检查。")
    if not record.mapping_confirmed:
        raise HTTPException(status_code=409, detail="请先确认字段和指标映射。")
    quality = QualityReport.model_validate(record.quality_report)
    if not quality.passed:
        raise HTTPException(status_code=409, detail="质量检查未通过，不能标记为可用。")
    try:
        return registry.update_status(
            dataset_id,
            DatasetStatus.READY,
            version=version,
            quality_report=quality,
        )
    except DatasetRegistryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/admin/datasets", response_model=tuple[DatasetRecord, ...])
def list_admin_datasets(
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[DatasetRegistry, Depends(get_dataset_registry)],
) -> tuple[DatasetRecord, ...]:
    _require_admin_access(access_context, settings)
    return registry.list_active()


@app.get("/admin/audit", response_model=list[AdminAuditEntry])
def read_admin_audit_entries(
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    connection: Annotated[
        DatabaseConnection,
        Depends(get_database_connection),
    ],
    request_id: Annotated[
        str | None,
        Query(min_length=1, max_length=200),
    ] = None,
    user_id: Annotated[
        str | None,
        Query(min_length=1, max_length=200),
    ] = None,
    status: AdminAuditStatus | None = None,
    agent_mode: AgentMode | None = None,
    approval_required: bool | None = None,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> tuple[AdminAuditEntry, ...]:
    _require_admin_access(access_context, settings)
    return list_admin_audit_entries(
        connection,
        request_id=request_id,
        user_id=user_id,
        agent_mode=agent_mode,
        status=status,
        approval_required=approval_required,
        days=days,
        limit=limit,
    )


@app.get("/admin/metrics", response_model=list[MetricDefinitionView])
def read_admin_metric_definitions(
    access_context: Annotated[AccessContext, Depends(get_access_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> tuple[MetricDefinitionView, ...]:
    _require_admin_access(access_context, settings)
    return list_metric_definitions()
