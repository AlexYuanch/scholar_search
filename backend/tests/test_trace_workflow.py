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
