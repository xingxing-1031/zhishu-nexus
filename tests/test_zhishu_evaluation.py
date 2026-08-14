from retail_analytics_agent.agent_models import (
    AgentMode,
    AgentResponse,
    AgentReview,
    AgentTaskStatus,
    KnowledgeEvidenceView,
    ToolCallRecord,
)
from retail_analytics_agent.zhishu_evaluation import (
    ZhishuEvaluationCase,
    evaluate_zhishu_cases,
    load_zhishu_cases,
)


def test_loads_jsonl_and_records_mode_tool_evidence_and_review() -> None:
    cases = load_zhishu_cases(
        [
            '{"case_id":"k1","question":"报销制度",'
            '"expected_mode":"knowledge","expected_tools":["knowledge.search"],'
            '"expect_knowledge_evidence":true}'
        ]
    )

    def execute(case: ZhishuEvaluationCase) -> AgentResponse:
        return AgentResponse(
            request_id=case.case_id,
            conversation_id="eval",
            status=AgentTaskStatus.SUCCEEDED,
            agent_mode=AgentMode.KNOWLEDGE,
            tool_calls=(
                ToolCallRecord(
                    request_id=case.case_id,
                    conversation_id="eval",
                    tool_name="knowledge.search",
                    input_hash="a" * 64,
                    status="succeeded",
                ),
            ),
            knowledge_evidence=(
                KnowledgeEvidenceView(
                    source_id="policy@1",
                    title="报销制度",
                    version="1",
                    quote="提交发票。",
                    score=0.9,
                ),
            ),
            review=AgentReview(passed=True),
        )

    report = evaluate_zhishu_cases(cases, execute, dataset="unit.jsonl")

    assert report.total == 1
    assert report.executed == 1
    assert report.mode_accuracy == 1
    assert report.tool_accuracy == 1
    assert report.evidence_accuracy == 1
    assert report.review_pass_rate == 1


def test_execution_failure_remains_in_denominator() -> None:
    case = ZhishuEvaluationCase(
        case_id="failure",
        question="天气",
        expected_mode=AgentMode.GENERAL,
        expected_tools=("weather.current",),
    )

    report = evaluate_zhishu_cases(
        [case],
        lambda _case: (_ for _ in ()).throw(TimeoutError()),
        dataset="unit.jsonl",
    )

    assert report.executed == 0
    assert report.mode_accuracy == 0
    assert report.cases[0].error_type == "TimeoutError"
