from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field

from retail_analytics_agent.agent_models import (
    AgentMode,
    AgentRequest,
    AgentResponse,
    AgentReview,
    AgentStep,
    AgentStreamEvent,
    AgentTaskStatus,
    KnowledgeEvidenceView,
    ToolCallRecord,
)
from retail_analytics_agent.agent_service import EnterpriseAgentService
from retail_analytics_agent.brand_identity import EVIDENCE_ANSWER_SYSTEM_PROMPT
from retail_analytics_agent.general_agent import GeneralAgent, GeneralAgentResult
from retail_analytics_agent.knowledge_adapter import (
    KnowledgeEvidence,
    KnowledgeQuery,
    KnowledgeRetriever,
)
from retail_analytics_agent.models import AccessContext
from retail_analytics_agent.supervisor import AgentPlan, Supervisor


class EvidenceAnswerer(Protocol):
    def answer(
        self,
        question: str,
        history: Sequence[dict[str, str]],
        evidence: Sequence[dict[str, object]],
        data: dict[str, object] | None = None,
    ) -> str: ...


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=12000)


class StructuredEvidenceAnswerer:
    def __init__(self, model: Any, *, model_name: str, timeout_seconds: float):
        self._model = model
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds

    def answer(
        self,
        question: str,
        history: Sequence[dict[str, str]],
        evidence: Sequence[dict[str, object]],
        data: dict[str, object] | None = None,
    ) -> str:
        raw = self._model.complete_json(
            model=self._model_name,
            system_prompt=EVIDENCE_ANSWER_SYSTEM_PROMPT,
            user_payload={
                "question": question,
                "history": list(history)[-6:],
                "knowledge_evidence": list(evidence),
                "data_evidence": data or {},
            },
            response_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
            timeout_seconds=self._timeout_seconds,
        )
        return _Answer.model_validate_json(raw).answer.strip()


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _history_from_store(service: EnterpriseAgentService, request: AgentRequest) -> list[dict[str, str]]:
    record = service.context_builder.store.get(request.conversation_id, request.user_id)
    if record is None:
        return []
    return [
        {"role": turn.role, "content": turn.content}
        for turn in record.turns[-8:]
    ]


def _context_snapshot(
    request: AgentRequest,
    history: Sequence[dict[str, str]],
    plan: AgentPlan,
) -> dict[str, object]:
    lines = [
        f"mode={plan.mode.value}",
        f"question={request.question}",
        *(f"{item['role']}: {item['content']}" for item in history[-6:]),
    ]
    summary = "\n".join(lines)
    return {
        "conversation_id": request.conversation_id,
        "task_goal": request.question,
        "summary": summary[: request.token_budget * 3],
        "token_budget": request.token_budget,
        "token_estimate": max(1, len(summary) // 3),
        "truncated": len(summary) > request.token_budget * 3,
    }


@dataclass
class ZhishuAgentService:
    data_agent: EnterpriseAgentService
    supervisor: Supervisor
    general_agent: GeneralAgent
    knowledge: KnowledgeRetriever | None
    answerer: EvidenceAnswerer
    knowledge_departments: tuple[str, ...] = ()

    def _prepare(
        self,
        request: AgentRequest,
    ) -> tuple[list[dict[str, str]], AgentPlan]:
        history = _history_from_store(self.data_agent, request)
        record = self.data_agent.context_builder.store.get(
            request.conversation_id,
            request.user_id,
        )
        previous_mode = None
        for constraint in reversed(
            record.confirmed_constraints if record is not None else ()
        ):
            if not constraint.startswith("last_agent_mode="):
                continue
            try:
                previous_mode = AgentMode(
                    constraint.removeprefix("last_agent_mode=")
                )
            except ValueError:
                previous_mode = None
            break
        plan = self.supervisor.plan(
            request.question,
            history,
            previous_mode=previous_mode,
        )
        return history, plan

    def run(
        self,
        request: AgentRequest,
        access_context: AccessContext,
    ) -> AgentResponse:
        if request.user_id != access_context.user_id:
            raise PermissionError("agent request belongs to another user")
        history, plan = self._prepare(request)
        self._append_user_turn(request)
        result = self._execute(request, access_context, plan, history)
        self._append_final_turn(request, result)
        return result

    def _execute(
        self,
        request: AgentRequest,
        access_context: AccessContext,
        plan: AgentPlan,
        history: Sequence[dict[str, str]],
    ) -> AgentResponse:
        if plan.mode is AgentMode.GENERAL:
            return self._run_general(request, access_context, plan, history)
        if plan.mode is AgentMode.KNOWLEDGE:
            return self._run_knowledge(request, access_context, plan, history)
        if plan.mode is AgentMode.DATA:
            return self._run_data(request, access_context, plan)
        return self._run_collaboration(request, access_context, plan, history)

    def stream(
        self,
        request: AgentRequest,
        access_context: AccessContext,
    ):
        if request.user_id != access_context.user_id:
            raise PermissionError("agent request belongs to another user")
        history, plan = self._prepare(request)
        yield AgentStreamEvent(
            event="status",
            node="supervisor",
            message=f"已路由到 {plan.mode.value} Agent",
        )
        for step in plan.steps:
            yield AgentStreamEvent(
                event="status",
                node=step.agent,
                message=step.task,
            )
        try:
            self._append_user_turn(request)
            result = self._execute(request, access_context, plan, history)
            self._append_final_turn(request, result)
        except Exception as exc:
            yield AgentStreamEvent(event="error", node="review_agent", message=str(exc))
            return
        yield AgentStreamEvent(
            event="result",
            node="review_agent",
            message="知枢任务完成",
            response=result,
        )

    def _run_general(
        self,
        request: AgentRequest,
        access_context: AccessContext,
        plan: AgentPlan,
        history: Sequence[dict[str, str]],
    ) -> AgentResponse:
        result: GeneralAgentResult = self.general_agent.answer(
            request.question,
            history,
            request.request_id,
            request.conversation_id,
            access_context.role.value,
        )
        review = AgentReview(
            passed=bool(result.answer),
            checks={"general_answer_present": bool(result.answer)},
            limitations=result.limitations,
        )
        return AgentResponse(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            status=result.status,
            agent_mode=AgentMode.GENERAL,
            agents=("general_agent", "review_agent"),
            agent_steps=self._completed_steps(plan.steps, result.status),
            answer=result.answer,
            tool_calls=result.tool_calls,
            limitations=result.limitations,
            review=review,
            context=_context_snapshot(request, history, plan),
        )

    def _run_knowledge(
        self,
        request: AgentRequest,
        access_context: AccessContext,
        plan: AgentPlan,
        history: Sequence[dict[str, str]],
    ) -> AgentResponse:
        evidence, call, limitations = self._retrieve_knowledge(
            request,
            access_context,
        )
        evidence_views = tuple(self._evidence_view(item) for item in evidence)
        answer = ""
        if evidence_views:
            answer = self.answerer.answer(
                request.question,
                history,
                [item.model_dump(mode="json") for item in evidence_views],
            )
        else:
            limitations.append("没有获得足够的企业知识证据")
        status = AgentTaskStatus.SUCCEEDED if answer and not limitations else AgentTaskStatus.DEGRADED
        if not answer:
            status = AgentTaskStatus.REFUSED
            answer = "当前没有足够的企业知识证据支持回答。"
        review = AgentReview(
            passed=bool(evidence_views) and bool(answer),
            checks={"knowledge_evidence_present": bool(evidence_views)},
            limitations=tuple(limitations),
        )
        return AgentResponse(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            status=status,
            agent_mode=AgentMode.KNOWLEDGE,
            agents=("knowledge_agent", "review_agent"),
            agent_steps=self._completed_steps(plan.steps, status),
            answer=answer,
            tool_calls=(call,) if call else (),
            limitations=tuple(limitations),
            knowledge_evidence=evidence_views,
            review=review,
            context=_context_snapshot(request, history, plan),
        )

    def _run_data(
        self,
        request: AgentRequest,
        access_context: AccessContext,
        plan: AgentPlan,
    ) -> AgentResponse:
        data_request = request.model_copy(update={"include_knowledge": False})
        result = self.data_agent.run(
            data_request,
            access_context,
            persist_context=False,
        )
        answer = result.answer or (
            result.report.executive_summary if result.report is not None else ""
        )
        status = result.status
        review = AgentReview(
            passed=bool(result.report and result.report.data_evidence),
            checks={"data_evidence_present": bool(result.report and result.report.data_evidence)},
            limitations=result.limitations,
        )
        return result.model_copy(
            update={
                "agent_mode": AgentMode.DATA,
                "agents": ("data_agent", "review_agent"),
                "agent_steps": self._completed_steps(plan.steps, status),
                "answer": answer,
                "review": review,
            }
        )

    def _run_collaboration(
        self,
        request: AgentRequest,
        access_context: AccessContext,
        plan: AgentPlan,
        history: Sequence[dict[str, str]],
    ) -> AgentResponse:
        data_request = request.model_copy(
            update={
                "include_knowledge": False,
                "question": _data_only_question(request.question),
            }
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            knowledge_future = executor.submit(
                self._retrieve_knowledge,
                request,
                access_context,
            )
            data_future = executor.submit(
                self.data_agent.run,
                data_request,
                access_context,
                persist_context=False,
            )
            evidence, knowledge_call, limitations = knowledge_future.result()
            data_result = data_future.result()
        views = tuple(self._evidence_view(item) for item in evidence)
        data_payload = {
            "answer": data_result.answer,
            "report": data_result.report.model_dump(mode="json") if data_result.report else None,
        }
        if views and data_result.report and data_result.report.data_evidence:
            answer = self.answerer.answer(
                request.question,
                history,
                [item.model_dump(mode="json") for item in views],
                data_payload,
            )
        else:
            answer = "\n\n".join(
                item for item in (data_result.answer, data_result.report.executive_summary if data_result.report else "") if item
            )
            limitations.append("制度证据或经营数据证据不完整，未形成完整跨域结论")
        if not views:
            limitations.append("没有获得足够的企业知识证据")
        if not data_result.report or not data_result.report.data_evidence:
            limitations.append("没有获得可引用的经营数据证据")
        status = AgentTaskStatus.SUCCEEDED if not limitations else AgentTaskStatus.DEGRADED
        calls = list(data_result.tool_calls)
        if knowledge_call:
            calls.append(knowledge_call)
        review = AgentReview(
            passed=bool(views and data_result.report and data_result.report.data_evidence),
            checks={
                "knowledge_evidence_present": bool(views),
                "data_evidence_present": bool(data_result.report and data_result.report.data_evidence),
                "required_agents_completed": True,
            },
            limitations=tuple(limitations),
        )
        return data_result.model_copy(
            update={
                "status": status,
                "agent_mode": AgentMode.COLLABORATION,
                "agents": ("knowledge_agent", "data_agent", "synthesis_agent", "review_agent"),
                "agent_steps": self._completed_steps(plan.steps, status),
                "answer": answer,
                "tool_calls": tuple(calls),
                "limitations": tuple(dict.fromkeys(limitations)),
                "knowledge_evidence": views,
                "review": review,
            }
        )

    def _retrieve_knowledge(
        self,
        request: AgentRequest,
        access_context: AccessContext,
    ) -> tuple[tuple[KnowledgeEvidence, ...], ToolCallRecord | None, list[str]]:
        started = monotonic()
        arguments = {
            "query": request.question,
            "user_id": request.user_id,
            "role": access_context.role.value,
            "departments": self.knowledge_departments,
            "top_k": 6,
        }
        input_hash = _hash_payload(arguments)
        if self.knowledge is None:
            return (), ToolCallRecord(
                request_id=request.request_id,
                conversation_id=request.conversation_id,
                tool_name="knowledge.search",
                input_hash=input_hash,
                status="failed",
                error_type="KnowledgeServiceUnavailable",
            ), ["企业知识服务未配置"]
        try:
            items = self.knowledge.retrieve(KnowledgeQuery(**arguments))
            call = ToolCallRecord(
                request_id=request.request_id,
                conversation_id=request.conversation_id,
                tool_name="knowledge.search",
                input_hash=input_hash,
                status="succeeded",
                duration_ms=int((monotonic() - started) * 1000),
            )
            return items, call, []
        except Exception as exc:
            call = ToolCallRecord(
                request_id=request.request_id,
                conversation_id=request.conversation_id,
                tool_name="knowledge.search",
                input_hash=input_hash,
                status="failed",
                duration_ms=int((monotonic() - started) * 1000),
                error_type=type(exc).__name__,
            )
            return (), call, ["企业知识服务暂时不可用"]

    @staticmethod
    def _evidence_view(item: KnowledgeEvidence) -> KnowledgeEvidenceView:
        effective_from = item.effective_from.isoformat() if item.effective_from else None
        return KnowledgeEvidenceView(
            source_id=item.source_id,
            title=item.title,
            version=item.version,
            quote=item.quote,
            score=item.score,
            effective_from=effective_from,
        )

    @staticmethod
    def _completed_steps(
        steps: Sequence[AgentStep],
        status: AgentTaskStatus,
    ) -> tuple[AgentStep, ...]:
        step_status = status if status in {
            AgentTaskStatus.SUCCEEDED,
            AgentTaskStatus.DEGRADED,
            AgentTaskStatus.REFUSED,
            AgentTaskStatus.FAILED,
        } else AgentTaskStatus.DEGRADED
        return tuple(item.model_copy(update={"status": step_status}) for item in steps)

    def _append_user_turn(self, request: AgentRequest) -> None:
        self.data_agent.context_builder.append_turn(
            request.conversation_id,
            request.user_id,
            request_id=f"{request.request_id}:user",
            role="user",
            content=request.question,
        )

    def _append_final_turn(
        self,
        request: AgentRequest,
        response: AgentResponse,
    ) -> None:
        answer = response.answer
        if not answer and response.report is not None:
            answer = response.report.executive_summary
        if not answer and response.limitations:
            answer = response.limitations[0]
        if not answer:
            answer = "当前任务未生成可展示的最终结果。"
        evidence_ids = [item.source_id for item in response.knowledge_evidence]
        if response.report is not None:
            evidence_ids.extend(response.report.data_evidence)
            evidence_ids.extend(response.report.document_evidence)
        constraints = [f"last_agent_mode={response.agent_mode.value}"]
        if response.skill_id is not None:
            constraints.append(f"last_skill={response.skill_id.value}")
        self.data_agent.context_builder.append_turn(
            request.conversation_id,
            request.user_id,
            request_id=f"{request.request_id}:assistant",
            role="assistant",
            content=answer,
            evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            confirmed_constraints=tuple(constraints),
        )


def _data_only_question(question: str) -> str:
    """Keep policy language out of the SQL planner for cross-domain tasks."""
    markers = ("并结合", "同时结合", "结合", "并参考", "同时参考")
    for marker in markers:
        prefix, separator, _suffix = question.partition(marker)
        if separator and prefix.strip():
            return f"{prefix.strip(' ，,。；;')}。"
    for marker in ("和售后制度", "和公司制度", "和制度"):
        prefix, separator, _suffix = question.partition(marker)
        if separator and prefix.strip():
            return f"{prefix.replace('结合', '').strip(' ，,。；;')}。"
    return question
