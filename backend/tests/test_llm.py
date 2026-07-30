from datetime import date

import llm


def _configure(monkeypatch):
    monkeypatch.delenv("LONGCAT_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_FAST_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("LLM_STRONG_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("LLM_ROUTER_MODE", "auto")
    monkeypatch.setenv("LLM_STRONG_DAILY_LIMIT", "100")
    monkeypatch.setattr(llm, "_strong_usage_date", date.today())
    monkeypatch.setattr(llm, "_strong_usage_count", 0)


def test_router_agent_chooses_models_from_complexity(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(llm, "_invoke_json", lambda model, *_args, **_kwargs: {
        "topic_tier": "strong",
        "trajectory_tier": "fast",
        "report_tier": "fast",
        "review_tier": "strong",
        "rationale": "identity ambiguity and metadata conflicts",
    })

    plan, trace = llm.plan_agents({
        "paper_count": 180,
        "source_conflicts": 8,
        "identity_risk": True,
    })

    assert plan.topic_tier == "strong"
    assert plan.review_tier == "strong"
    assert trace["status"] == "success"
    assert trace["model"] == "deepseek-v4-flash"


def test_structured_agent_escalates_invalid_flash_result_to_pro(monkeypatch):
    _configure(monkeypatch)

    def fake_invoke(model, *_args, **_kwargs):
        if model == "deepseek-v4-flash":
            return {
                "summary_zh": "bad",
                "summary_en": "bad",
                "evidence_ids": [],
                "confidence": "low",
            }
        return {
            "summary_zh": "有充分依据的学者总结 [1]，并且包含足够长度用于通过验证。",
            "summary_en": "A sufficiently supported scholar summary with traceable evidence [1].",
            "evidence_ids": ["1"],
            "confidence": "high",
        }

    monkeypatch.setattr(llm, "_invoke_json", fake_invoke)
    result, trace = llm.run_structured_agent(
        "report_agent",
        planned_tier="fast",
        system_prompt="test",
        payload={},
        schema=llm.ProfileReportOutput,
        validate=lambda output: ["too_short"] if output.summary_zh == "bad" else [],
    )

    assert result is not None
    assert result.confidence == "high"
    assert trace["model"] == "deepseek-v4-pro"
    assert trace["escalated"] is True
    assert trace["attemptedModels"] == ["deepseek-v4-flash", "deepseek-v4-pro"]


def test_strong_daily_limit_downgrades_to_flash(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("LLM_STRONG_DAILY_LIMIT", "0")
    monkeypatch.setattr(llm, "_invoke_json", lambda model, *_args, **_kwargs: {
        "summary_zh": "有充分依据的学者总结 [1]，并且包含足够长度用于通过验证。",
        "summary_en": "A sufficiently supported scholar summary with traceable evidence [1].",
        "evidence_ids": ["1"],
        "confidence": "medium",
    })

    result, trace = llm.run_structured_agent(
        "report_agent",
        planned_tier="strong",
        system_prompt="test",
        payload={},
        schema=llm.ProfileReportOutput,
        validate=lambda _output: [],
    )

    assert result is not None
    assert trace["model"] == "deepseek-v4-flash"
    assert "strong_daily_limit_reached" in trace["reasons"]


def test_placeholder_key_disables_agents(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "你的DeepSeek_API_Key")
    monkeypatch.setenv("LLM_ROUTER_MODE", "auto")

    result, trace = llm.run_structured_agent(
        "report_agent",
        planned_tier="fast",
        system_prompt="test",
        payload={},
        schema=llm.ProfileReportOutput,
        validate=lambda _output: [],
    )

    assert result is None
    assert trace["status"] == "disabled"
    assert trace["reasons"] == ["llm_not_configured"]


def test_longcat_is_used_before_deepseek(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("LONGCAT_API_KEY", "longcat-test-key")
    monkeypatch.setenv("LONGCAT_BASE_URL", "https://api.longcat.chat/openai")
    monkeypatch.setenv("LONGCAT_MODEL", "LongCat-2.0")

    def fake_invoke(model, *_args, provider="deepseek", **_kwargs):
        assert model == "LongCat-2.0"
        assert provider == "longcat"
        return {
            "summary_zh": "有充分依据的学者总结 [1]，并且包含足够长度用于通过验证。",
            "summary_en": "A sufficiently supported scholar summary with traceable evidence [1].",
            "evidence_ids": ["1"],
            "confidence": "high",
        }

    monkeypatch.setattr(llm, "_invoke_json", fake_invoke)
    result, trace = llm.run_structured_agent(
        "report_agent",
        planned_tier="strong",
        system_prompt="test",
        payload={},
        schema=llm.ProfileReportOutput,
        validate=lambda _output: [],
    )

    assert result is not None
    assert trace["provider"] == "longcat"
    assert trace["model"] == "LongCat-2.0"
    assert trace["attemptedProviders"] == ["longcat"]


def test_longcat_failure_falls_back_to_deepseek(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("LONGCAT_API_KEY", "longcat-test-key")

    def fake_invoke(model, *_args, provider="deepseek", **_kwargs):
        if provider == "longcat":
            raise RuntimeError("temporary failure")
        return {
            "summary_zh": "有充分依据的学者总结 [1]，并且包含足够长度用于通过验证。",
            "summary_en": "A sufficiently supported scholar summary with traceable evidence [1].",
            "evidence_ids": ["1"],
            "confidence": "medium",
        }

    monkeypatch.setattr(llm, "_invoke_json", fake_invoke)
    result, trace = llm.run_structured_agent(
        "report_agent",
        planned_tier="fast",
        system_prompt="test",
        payload={},
        schema=llm.ProfileReportOutput,
        validate=lambda _output: [],
    )

    assert result is not None
    assert trace["provider"] == "deepseek"
    assert trace["model"] == "deepseek-v4-flash"
    assert trace["attemptedModels"] == ["LongCat-2.0", "deepseek-v4-flash"]
    assert trace["attemptedProviders"] == ["longcat", "deepseek"]
    assert "longcat_fast_error:RuntimeError" in trace["reasons"]
