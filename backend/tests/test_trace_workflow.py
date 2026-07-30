from trace_workflow import _result_summary, _state_summary


def test_state_summary_redacts_credentials_and_compacts_works():
    summary = _state_summary({
        "target_author_id": "A123",
        "openalex_api_key": "secret-value",
        "raw_works": [{
            "id": "W1",
            "title": "A representative paper",
            "publication_year": 2025,
        }],
        "warnings": ["partial source"],
    })

    assert "openalex_api_key" not in summary
    assert summary["raw_works"] == {
        "count": 1,
        "sample": [{
            "id": "W1",
            "year": 2025,
            "title": "A representative paper",
        }],
    }
    assert summary["warnings"] == {"count": 1}


def test_result_summary_never_includes_sensitive_keys():
    summary = _result_summary({
        "agent_trace": {
            "provider": "longcat",
            "model": "LongCat-2.0",
            "access_token": "do-not-print",
        },
        "credential": "do-not-print",
    })

    assert "credential" not in summary
    assert summary["agent_trace"] == {
        "provider": "longcat",
        "model": "LongCat-2.0",
    }


def test_result_summary_exposes_sanitized_agent_and_worker_status():
    summary = _result_summary({
        "agent_runs": [{
            "agent": "topic_agent",
            "status": "success",
            "provider": "longcat",
            "model": "LongCat-2.0",
            "tier": "fast",
            "escalated": False,
            "reasons": ["validated"],
            "access_token": "do-not-print",
        }],
        "worker_outputs": [{
            "taskId": "representative_works",
            "kind": "representative_works",
            "confidence": 0.92,
            "evidenceIds": ["1", "2"],
            "findingZh": "sensitive long-form output",
        }],
    })

    assert summary["agent_runs"] == [{
        "agent": "topic_agent",
        "status": "success",
        "provider": "longcat",
        "model": "LongCat-2.0",
        "tier": "fast",
        "escalated": False,
        "reasons": ["validated"],
    }]
    assert summary["worker_outputs"] == [{
        "task_id": "representative_works",
        "kind": "representative_works",
        "confidence": 0.92,
        "evidence_count": 2,
    }]
