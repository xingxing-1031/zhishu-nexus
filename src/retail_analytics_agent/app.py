import asyncio
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from retail_analytics_agent.access_control import get_access_context
from retail_analytics_agent.analysis_service import (
    AnalysisRequestConflictError,
    AnalysisRunError,
    AnalysisRunner,
    get_analysis_runner,
)
from retail_analytics_agent.database import (
    DatabaseConnection,
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
)
from retail_analytics_agent.model_adapters import ModelInvocationError
from retail_analytics_agent.queries import (
    get_channel_sales_summary,
    get_order_status_summary,
    get_product_sales_summary,
    get_refund_status_summary,
)
from retail_analytics_agent.tracing import ExecutionTraceResponse


app = FastAPI(
    title="Retail Analytics Agent",
    version="0.1.0",
)
_STATIC_DIR = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def read_demo() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/session", response_model=AccessContext)
def read_session(
    access_context: Annotated[AccessContext, Depends(get_access_context)],
) -> AccessContext:
    return access_context


@app.post("/analysis/validate")
def validate_analysis_request(
    request: AnalysisRequest,
) -> AnalysisRequest:
    return request


@app.post("/analysis/run", response_model=AnalysisOutcome)
def run_analysis(
    request: AnalysisRequest,
    response: Response,
    runner: Annotated[AnalysisRunner, Depends(get_analysis_runner)],
    access_context: Annotated[AccessContext, Depends(get_access_context)],
) -> AnalysisOutcome:
    if request.user_id != access_context.user_id:
        raise HTTPException(
            status_code=403,
            detail="request user_id does not match authenticated user",
        )
    try:
        result = runner.run(request, access_context)
        if isinstance(
            result,
            (ApprovalRequiredResponse, AnalysisRunningResponse),
        ):
            response.status_code = 202
        return result
    except AnalysisRequestConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ModelInvocationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AnalysisRunError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post(
    "/analysis/{request_id}/approval",
    response_model=AnalysisOutcome,
)
def resolve_analysis_approval(
    request_id: str,
    resolution: ApprovalResolutionRequest,
    runner: Annotated[AnalysisRunner, Depends(get_analysis_runner)],
    access_context: Annotated[AccessContext, Depends(get_access_context)],
) -> AnalysisOutcome:
    if access_context.role is not AccessRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="only an admin can resolve approvals",
        )
    try:
        return runner.resume_approval(
            request_id,
            resolution,
            access_context,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/analysis/{request_id}",
    response_model=AnalysisOutcome,
)
def read_analysis_status(
    request_id: str,
    runner: Annotated[AnalysisRunner, Depends(get_analysis_runner)],
    access_context: Annotated[AccessContext, Depends(get_access_context)],
) -> AnalysisOutcome:
    try:
        return runner.get_status(request_id, access_context)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/analysis/{request_id}/trace",
    response_model=ExecutionTraceResponse,
)
def read_analysis_trace(
    request_id: str,
    runner: Annotated[AnalysisRunner, Depends(get_analysis_runner)],
    access_context: Annotated[AccessContext, Depends(get_access_context)],
) -> ExecutionTraceResponse:
    try:
        return runner.get_trace(request_id, access_context)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
                message=str(item),
            )
        else:
            event = item
        yield (
            f"event: {event.event.value}\n"
            f"data: {event.model_dump_json()}\n\n"
        )


@app.post("/analysis/stream")
def stream_analysis(
    request: AnalysisRequest,
    runner: Annotated[AnalysisRunner, Depends(get_analysis_runner)],
    access_context: Annotated[AccessContext, Depends(get_access_context)],
) -> StreamingResponse:
    if request.user_id != access_context.user_id:
        raise HTTPException(
            status_code=403,
            detail="request user_id does not match authenticated user",
        )
    return StreamingResponse(
        _encode_analysis_events(runner, request, access_context),
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
    connection: Annotated[
        DatabaseConnection,
        Depends(get_database_connection),
    ],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> list[OrderStatusSummary]:
    return get_order_status_summary(connection, days=days)
