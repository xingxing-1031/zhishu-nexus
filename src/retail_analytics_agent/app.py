from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse

from retail_analytics_agent.access_control import get_access_context
from retail_analytics_agent.analysis_service import (
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
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStreamEvent,
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


app = FastAPI(
    title="Retail Analytics Agent",
    version="0.1.0",
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analysis/validate")
def validate_analysis_request(
    request: AnalysisRequest,
) -> AnalysisRequest:
    return request


@app.post("/analysis/run", response_model=AnalysisResponse)
def run_analysis(
    request: AnalysisRequest,
    runner: Annotated[AnalysisRunner, Depends(get_analysis_runner)],
    access_context: Annotated[AccessContext, Depends(get_access_context)],
) -> AnalysisResponse:
    if request.user_id != access_context.user_id:
        raise HTTPException(
            status_code=403,
            detail="request user_id does not match authenticated user",
        )
    try:
        return runner.run(request, access_context)
    except ModelInvocationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AnalysisRunError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _encode_analysis_events(
    runner: AnalysisRunner,
    request: AnalysisRequest,
    access_context: AccessContext,
):
    try:
        for event in runner.stream(request, access_context):
            yield f"event: {event.event.value}\ndata: {event.model_dump_json()}\n\n"
    except Exception as exc:
        event = AnalysisStreamEvent(
            event="error",
            message=str(exc),
        )
        yield f"event: error\ndata: {event.model_dump_json()}\n\n"


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
