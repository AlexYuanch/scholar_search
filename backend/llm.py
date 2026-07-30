"""OpenAI-compatible LLM agents with model routing and safe fallbacks."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import date
from typing import Callable, Literal, TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from prompts import AGENT_ORCHESTRATOR, AGENT_ROUTER, AGENT_WORKER


AgentTier = Literal["fast", "strong"]
SchemaType = TypeVar("SchemaType", bound=BaseModel)


class AgentPlan(BaseModel):
    topic_tier: AgentTier = "fast"
    trajectory_tier: AgentTier = "fast"
    report_tier: AgentTier = "fast"
    review_tier: AgentTier = "fast"
    rationale: str = ""


class TopicDirection(BaseModel):
    name: str
    description_zh: str
    description_en: str
    source_topics: list[str]
    confidence: Literal["high", "medium", "low"] = "medium"


class TopicAgentOutput(BaseModel):
    directions: list[TopicDirection]


class TrajectoryInsight(BaseModel):
    direction: str
    change_kind: Literal["emerging", "rising", "steady", "falling"]
    interpretation_zh: str
    interpretation_en: str
    evidence_work_ids: list[str]
    confidence: Literal["high", "medium", "low"] = "medium"


class TrajectoryAgentOutput(BaseModel):
    summary_zh: str
    summary_en: str
    emerging: list[str] = Field(default_factory=list)
    rising: list[str] = Field(default_factory=list)
    steady: list[str] = Field(default_factory=list)
    falling: list[str] = Field(default_factory=list)
    insights: list[TrajectoryInsight] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


class ProfileReportOutput(BaseModel):
    summary_zh: str
    summary_en: str
    evidence_ids: list[str]
    confidence: Literal["high", "medium", "low"] = "medium"


class EvidenceReviewOutput(BaseModel):
    summary_supported: bool
    approved_evidence_ids: list[str]
    flags: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    note_zh: str = ""
    note_en: str = ""


WorkerKind = Literal[
    "representative_works",
    "collaboration_opportunities",
    "institution_positioning",
    "research_continuity",
]


class OrchestratorTask(BaseModel):
    id: str
    kind: WorkerKind
    objective: str
    rationale: str = ""
    tier: AgentTier = "fast"


class OrchestratorPlan(BaseModel):
    tasks: list[OrchestratorTask] = Field(default_factory=list, max_length=4)
    rationale: str = ""


class AcademicWorkerOutput(BaseModel):
    task_id: str
    kind: WorkerKind
    finding_zh: str
    finding_en: str
    evidence_ids: list[str]
    confidence: Literal["high", "medium", "low"] = "medium"
    limitations_zh: str = ""
    limitations_en: str = ""


_usage_lock = threading.Lock()
_strong_usage_date = date.today()
_strong_usage_count = 0


@dataclass(frozen=True)
class ProviderAttempt:
    provider: str
    model: str
    tier: AgentTier


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _deepseek_api_key() -> str:
    return _env("LLM_API_KEY") or _env("OPENAI_API_KEY")


def _deepseek_base_url() -> str:
    return (_env("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")


def _fast_model() -> str:
    return _env("LLM_FAST_MODEL") or _env("LLM_MODEL") or "gpt-4o-mini"


def _strong_model() -> str:
    return _env("LLM_STRONG_MODEL") or _fast_model()


def _longcat_api_key() -> str:
    return _env("LONGCAT_API_KEY")


def _longcat_base_url() -> str:
    return (_env("LONGCAT_BASE_URL") or "https://api.longcat.chat/openai").rstrip("/")


def _longcat_model() -> str:
    return _env("LONGCAT_MODEL") or "LongCat-2.0"


def _router_mode() -> str:
    mode = _env("LLM_ROUTER_MODE", "auto").lower()
    return mode if mode in {"auto", "fast", "strong", "off"} else "auto"


def _valid_key(key: str) -> bool:
    lowered = key.casefold()
    placeholders = ("your_api", "your-api", "你的", "replace_with")
    return bool(key and not any(marker in lowered for marker in placeholders))


def _deepseek_configured() -> bool:
    return _valid_key(_deepseek_api_key())


def _longcat_configured() -> bool:
    return _valid_key(_longcat_api_key())


def _configured() -> bool:
    return _longcat_configured() or _deepseek_configured()


def _strong_limit() -> int:
    try:
        return max(0, int(_env("LLM_STRONG_DAILY_LIMIT", "100")))
    except ValueError:
        return 100


def _reserve_strong_slot() -> bool:
    global _strong_usage_date, _strong_usage_count
    with _usage_lock:
        today = date.today()
        if today != _strong_usage_date:
            _strong_usage_date = today
            _strong_usage_count = 0
        limit = _strong_limit()
        if limit <= 0 or _strong_usage_count >= limit:
            return False
        _strong_usage_count += 1
        return True


def _llm(model: str, *, provider: str = "deepseek", **kwargs) -> ChatOpenAI:
    if provider == "longcat":
        return ChatOpenAI(
            api_key=_longcat_api_key(),
            base_url=_longcat_base_url(),
            model=model,
            extra_body={"thinking": {"type": "disabled"}},
            **kwargs,
        )
    return ChatOpenAI(
        api_key=_deepseek_api_key(),
        base_url=_deepseek_base_url(),
        model=model,
        **kwargs,
    )


def _json_content(content: str) -> dict:
    text = str(content or "").strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    return json.loads(text)


def _invoke_json(
    model: str,
    system_prompt: str,
    payload: dict,
    *,
    provider: str = "deepseek",
    temperature: float,
    max_tokens: int,
) -> dict:
    response = _llm(
        model,
        provider=provider,
        temperature=temperature,
        max_tokens=max_tokens,
    ).invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ])
    return _json_content(response.content)


def _trace(
    agent: str,
    *,
    status: str,
    model: str = "",
    provider: str = "",
    tier: str = "",
    planned_tier: str = "",
    attempted_models: list[str] | None = None,
    attempted_providers: list[str] | None = None,
    escalated: bool = False,
    reasons: list[str] | None = None,
) -> dict:
    return {
        "agent": agent,
        "status": status,
        "model": model,
        "provider": provider,
        "tier": tier,
        "plannedTier": planned_tier,
        "attemptedModels": attempted_models or [],
        "attemptedProviders": attempted_providers or [],
        "escalated": escalated,
        "reasons": reasons or [],
    }


def _router_attempts() -> list[ProviderAttempt]:
    attempts = []
    if _longcat_configured():
        attempts.append(ProviderAttempt("longcat", _longcat_model(), "fast"))
    if _deepseek_configured():
        attempts.append(ProviderAttempt("deepseek", _fast_model(), "fast"))
    return attempts


def _agent_attempts(selected_tier: AgentTier, mode: str) -> list[ProviderAttempt]:
    attempts = []
    if _longcat_configured():
        attempts.append(ProviderAttempt("longcat", _longcat_model(), selected_tier))
    if not _deepseek_configured():
        return attempts
    tiers: list[AgentTier] = [selected_tier]
    if mode == "auto":
        tiers.append("strong" if selected_tier == "fast" else "fast")
    for tier in tiers:
        attempts.append(ProviderAttempt(
            "deepseek",
            _strong_model() if tier == "strong" else _fast_model(),
            tier,
        ))
    return attempts


def _fallback_plan(context: dict) -> AgentPlan:
    conflicts = int(context.get("source_conflicts") or 0)
    papers = int(context.get("paper_count") or 0)
    identity_risk = bool(context.get("identity_risk"))
    broad_span = bool(context.get("broad_topic_span"))
    return AgentPlan(
        topic_tier="strong" if identity_risk or broad_span or papers >= 300 else "fast",
        trajectory_tier="strong" if broad_span or int(context.get("active_years") or 0) >= 15 else "fast",
        report_tier="strong" if conflicts >= 8 or identity_risk else "fast",
        review_tier="strong" if conflicts >= 3 or identity_risk else "fast",
        rationale="deterministic_fallback",
    )


def plan_agents(context: dict) -> tuple[AgentPlan, dict]:
    mode = _router_mode()
    fallback = _fallback_plan(context)
    if not _configured() or mode == "off":
        return fallback, _trace(
            "router_agent",
            status="disabled",
            planned_tier="fast",
            reasons=["llm_not_configured" if not _configured() else "router_off"],
        )
    if mode in {"fast", "strong"}:
        plan = AgentPlan(
            topic_tier=mode,
            trajectory_tier=mode,
            report_tier=mode,
            review_tier=mode,
            rationale=f"forced_{mode}",
        )
        return plan, _trace(
            "router_agent",
            status="policy",
            tier=mode,
            planned_tier=mode,
            reasons=[f"forced_{mode}"],
        )

    attempted_models = []
    attempted_providers = []
    reasons = []
    for attempt in _router_attempts():
        attempted_models.append(attempt.model)
        attempted_providers.append(attempt.provider)
        try:
            result = AgentPlan.model_validate(_invoke_json(
                attempt.model,
                AGENT_ROUTER,
                context,
                provider=attempt.provider,
                temperature=0,
                max_tokens=350,
            ))
            return result, _trace(
                "router_agent",
                status="success",
                model=attempt.model,
                provider=attempt.provider,
                tier="fast",
                planned_tier="fast",
                attempted_models=attempted_models,
                attempted_providers=attempted_providers,
                reasons=reasons + ([result.rationale] if result.rationale else []),
            )
        except Exception as exc:
            reasons.append(f"{attempt.provider}_router_error:{type(exc).__name__}")
    return fallback, _trace(
        "router_agent",
        status="fallback",
        tier="fast",
        planned_tier="fast",
        attempted_models=attempted_models,
        attempted_providers=attempted_providers,
        reasons=reasons + [fallback.rationale],
    )


def _fallback_orchestrator_plan(context: dict) -> OrchestratorPlan:
    tasks = []
    default_tier: AgentTier = (
        "strong"
        if bool(context.get("identity_risk")) or int(context.get("source_conflicts") or 0) >= 5
        else "fast"
    )

    def add(kind: WorkerKind, objective: str, rationale: str) -> None:
        tasks.append(OrchestratorTask(
            id=kind,
            kind=kind,
            objective=objective,
            rationale=rationale,
            tier=default_tier,
        ))

    if int(context.get("representative_paper_count") or 0) > 0:
        add("representative_works", "分析代表作解决的问题与贡献", "存在可追溯代表论文")
    if int(context.get("coauthor_count") or 0) >= 2:
        add("collaboration_opportunities", "分析稳定合作关系与潜在合作对象", "合作证据足够")
    if int(context.get("institution_count") or 0) >= 2:
        add("institution_positioning", "分析论文关联机构与研究主题交集", "存在多个机构证据")
    if int(context.get("active_years") or 0) >= 4:
        add("research_continuity", "分析研究延续性与阶段变化", "时间跨度足够")
    return OrchestratorPlan(tasks=tasks[:4], rationale="deterministic_evidence_coverage")


def orchestrate_workers(context: dict) -> tuple[OrchestratorPlan, dict]:
    """Dynamically choose evidence-backed specialist workers for this scholar."""
    fallback = _fallback_orchestrator_plan(context)
    mode = _router_mode()
    if not _configured() or mode == "off":
        return fallback, _trace(
            "orchestrator_agent",
            status="disabled",
            planned_tier="fast",
            reasons=["llm_not_configured" if not _configured() else "router_off"],
        )

    attempted_models = []
    attempted_providers = []
    reasons = []
    for attempt in _router_attempts():
        attempted_models.append(attempt.model)
        attempted_providers.append(attempt.provider)
        try:
            plan = OrchestratorPlan.model_validate(_invoke_json(
                attempt.model,
                AGENT_ORCHESTRATOR,
                context,
                provider=attempt.provider,
                temperature=0,
                max_tokens=900,
            ))
            task_ids = [task.id for task in plan.tasks]
            task_kinds = [task.kind for task in plan.tasks]
            if len(task_ids) != len(set(task_ids)):
                reasons.append("duplicate_worker_task_id")
                continue
            if len(task_kinds) != len(set(task_kinds)):
                reasons.append("duplicate_worker_kind")
                continue
            return plan, _trace(
                "orchestrator_agent",
                status="success",
                model=attempt.model,
                provider=attempt.provider,
                tier="fast",
                planned_tier="fast",
                attempted_models=attempted_models,
                attempted_providers=attempted_providers,
                reasons=reasons + ([plan.rationale] if plan.rationale else []),
            )
        except Exception as exc:
            reasons.append(f"{attempt.provider}_orchestrator_error:{type(exc).__name__}")
    return fallback, _trace(
        "orchestrator_agent",
        status="fallback",
        planned_tier="fast",
        attempted_models=attempted_models,
        attempted_providers=attempted_providers,
        reasons=reasons + [fallback.rationale],
    )


def run_academic_worker(
    task: OrchestratorTask,
    context: dict,
) -> tuple[AcademicWorkerOutput | None, dict]:
    valid_ids = {
        str(item.get("id"))
        for item in context.get("evidence") or []
        if item.get("id") is not None
    }

    def validate(output: AcademicWorkerOutput) -> list[str]:
        issues = []
        if output.task_id != task.id or output.kind != task.kind:
            issues.append("worker_task_mismatch")
        evidence_ids = set(output.evidence_ids)
        if not evidence_ids or not evidence_ids <= valid_ids:
            issues.append("worker_unknown_evidence_id")
        if len(output.finding_zh.strip()) < 12 or len(output.finding_en.split()) < 8:
            issues.append("worker_finding_too_short")
        return issues

    return run_structured_agent(
        f"{task.kind}_worker",
        planned_tier=task.tier,
        system_prompt=AGENT_WORKER,
        payload={
            "task": task.model_dump(),
            **context,
        },
        schema=AcademicWorkerOutput,
        validate=validate,
        temperature=0.2,
        max_tokens=1100,
    )


def run_structured_agent(
    agent: str,
    *,
    planned_tier: AgentTier,
    system_prompt: str,
    payload: dict,
    schema: type[SchemaType],
    validate: Callable[[SchemaType], list[str]],
    temperature: float = 0.2,
    max_tokens: int = 1200,
) -> tuple[SchemaType | None, dict]:
    mode = _router_mode()
    if not _configured() or mode == "off":
        return None, _trace(
            agent,
            status="disabled",
            planned_tier=planned_tier,
            reasons=["llm_not_configured" if not _configured() else "router_off"],
        )

    selected_tier: AgentTier = (
        "fast" if mode == "fast"
        else "strong" if mode == "strong"
        else planned_tier
    )
    attempted_models: list[str] = []
    attempted_providers: list[str] = []
    reasons: list[str] = []
    first_tier = selected_tier
    seen = set()
    for index, attempt in enumerate(_agent_attempts(selected_tier, mode)):
        attempt_key = (attempt.provider, attempt.model)
        if attempt_key in seen:
            continue
        seen.add(attempt_key)
        if attempt.provider == "deepseek" and attempt.tier == "strong" and not _reserve_strong_slot():
            reasons.append("strong_daily_limit_reached")
            continue
        attempted_models.append(attempt.model)
        attempted_providers.append(attempt.provider)
        try:
            parsed = schema.model_validate(_invoke_json(
                attempt.model,
                system_prompt,
                payload,
                provider=attempt.provider,
                temperature=temperature,
                max_tokens=max_tokens,
            ))
            issues = validate(parsed)
            if issues:
                reasons.extend(issues)
                continue
            return parsed, _trace(
                agent,
                status="success",
                model=attempt.model,
                provider=attempt.provider,
                tier=attempt.tier,
                planned_tier=planned_tier,
                attempted_models=attempted_models,
                attempted_providers=attempted_providers,
                escalated=(
                    attempt.provider == "deepseek"
                    and index > 0
                    and attempt.tier == "strong"
                    and first_tier == "fast"
                ),
                reasons=reasons,
            )
        except Exception as exc:
            reasons.append(f"{attempt.provider}_{attempt.tier}_error:{type(exc).__name__}")

    return None, _trace(
        agent,
        status="fallback",
        planned_tier=planned_tier,
        attempted_models=attempted_models,
        attempted_providers=attempted_providers,
        escalated=len(attempted_models) > 1,
        reasons=reasons or ["no_valid_agent_output"],
    )
