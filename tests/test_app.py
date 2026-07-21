from fastapi.testclient import TestClient

from retail_analytics_agent.app import app


client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_validate_analysis_request_accepts_valid_data() -> None:
    response = client.post(
        "/analysis/validate",
        json={
            "request_id": "REQ-001",
            "user_id": "USER-001",
            "question": "最近30天各渠道销售额是多少？",
        },
    )

    assert response.status_code == 200
    assert response.json()["request_id"] == "REQ-001"
    assert response.json()["max_rows"] == 100


def test_validate_analysis_request_rejects_too_many_rows() -> None:
    response = client.post(
        "/analysis/validate",
        json={
            "request_id": "REQ-002",
            "user_id": "USER-001",
            "question": "查询全部订单",
            "max_rows": 1001,
        },
    )

    assert response.status_code == 422

    error = response.json()["detail"][0]

    assert error["loc"] == ["body", "max_rows"]
    assert error["type"] == "less_than_equal"