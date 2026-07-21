from fastapi import FastAPI

from retail_analytics_agent.models import AnalysisRequest


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
