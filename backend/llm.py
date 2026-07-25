"""OpenAI-compatible LLM agents with model routing and safe fallbacks."""
from __future__ import annotations

import json
import os
import threading
from datetime import date
from typing import Callable, Literal, TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from prompts import AGENT_ROUTER


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


class TrajectoryAgentOutput(BaseModel):
    summary_zh: str
    summary_en: str
    emerging: list[str] = Field(default_factory=list)
    rising: list[str] = Field(default_factory=list)
    steady: list[str] = Field(default_factory=list)
    falling: list[str] = Field(default_factory=list)
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


_usage_lock = threading.Lock()
_strong_usage_date = date.today()
_strong_usage_count = 0


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _api_key() -> str:
    return _env("LLM_API_KEY") or _env("OPENAI_API_KEY")


def _base_url() -> str:
    return (_env("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")


def _fast_model() -> str:
    return _env("LLM_FAST_MODEL") or _env("LLM_MODEL") or "gpt-4o-mini"


def _strong_model() -> str:
    return _env("LLM_STRONG_MODEL") or _fast_model()


def _router_mode() -> str:
    mode = _env("LLM_ROUTER_MODE", "auto").lower()
    return mode if mode in {"auto", "fast", "strong", "off"} else "auto"


def _configured() -> bool:
    key = _api_key()
    lowered = key.casefold()
    placeholders = ("your_api", "your-api", "你的", "replace_with")
    return bool(key and not any(marker in lowered for marker in placeholders))


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


def _llm(model: str, **kwargs) -> ChatOpenAI:
    return ChatOpenAI(
        api_key=_api_key(),
        base_url=_base_url(),
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
    temperature: float,
    max_tokens: int,
) -> dict:
    response = _llm(model, temperature=temperature, max_tokens=max_tokens).invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ])
    return _json_content(response.content)


def _trace(
    agent: str,
    *,
    status: str,
    model: str = "",
    tier: str = "",
    planned_tier: str = "",
    attempted_models: list[str] | None = None,
    escalated: bool = False,
    reasons: list[str] | None = None,
) -> dict:
    return {
        "agent": agent,
        "status": status,
        "model": model,
        "tier": tier,
        "plannedTier": planned_tier,
        "attemptedModels": attempted_models or [],
        "escalated": escalated,
        "reasons": reasons or [],
    }


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

    model = _fast_model()
    try:
        result = AgentPlan.model_validate(_invoke_json(
            model,
            AGENT_ROUTER,
            context,
            temperature=0,
            max_tokens=350,
        ))
        return result, _trace(
            "router_agent",
            status="success",
            model=model,
            tier="fast",
            planned_tier="fast",
            attempted_models=[model],
            reasons=[result.rationale] if result.rationale else [],
        )
    except Exception as exc:
        return fallback, _trace(
            "router_agent",
            status="fallback",
            model=model,
            tier="fast",
            planned_tier="fast",
            attempted_models=[model],
            reasons=[f"router_error:{type(exc).__name__}", fallback.rationale],
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
    tiers: list[AgentTier] = [selected_tier]
    if mode == "auto":
        tiers.append("strong" if selected_tier == "fast" else "fast")

    attempted_models: list[str] = []
    reasons: list[str] = []
    first_tier = tiers[0]
    for index, tier in enumerate(tiers):
        model = _strong_model() if tier == "strong" else _fast_model()
        if model in attempted_models:
            continue
        if tier == "strong" and not _reserve_strong_slot():
            reasons.append("strong_daily_limit_reached")
            continue
        attempted_models.append(model)
        try:
            parsed = schema.model_validate(_invoke_json(
                model,
                system_prompt,
                payload,
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
                model=model,
                tier=tier,
                planned_tier=planned_tier,
                attempted_models=attempted_models,
                escalated=index > 0 and tier == "strong" and first_tier == "fast",
                reasons=reasons,
            )
        except Exception as exc:
            reasons.append(f"{tier}_error:{type(exc).__name__}")

    return None, _trace(
        agent,
        status="fallback",
        planned_tier=planned_tier,
        attempted_models=attempted_models,
        escalated=len(attempted_models) > 1,
        reasons=reasons or ["no_valid_agent_output"],
    )
