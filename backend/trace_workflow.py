"""Run a production-like scholar workflow with sanitized per-node tracing."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from state import default_state
from workflow import graph


SENSITIVE_MARKERS = ("api_key", "password", "secret", "token", "credential")
WORK_LIST_KEYS = {
    "raw_works",
    "deduped_works",
    "adjudicated_works",
    "orcid_works",
    "provisional_works",
}


def _safe_text(value: Any, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _work_sample(items: list[Any]) -> list[dict[str, Any]]:
    sample = []
    for item in items[:2]:
        if not isinstance(item, dict):
            continue
        sample.append({
            "id": _safe_text(item.get("id") or item.get("doi"), 72),
            "year": item.get("publication_year") or item.get("year"),
            "title": _safe_text(item.get("title"), 96),
        })
    return sample


def _profile_summary(profile: Any) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return {}
    institutions = profile.get("last_known_institutions") or profile.get("institutions") or []
    return {
        "id": _safe_text(profile.get("id"), 72),
        "name": _safe_text(profile.get("display_name") or profile.get("name"), 80),
        "orcid": _safe_text(profile.get("orcid"), 48),
        "works_count": profile.get("works_count"),
        "institution_count": len(institutions) if isinstance(institutions, list) else 0,
    }


def _compact_value(key: str, value: Any) -> Any:
    normalized_key = key.casefold()
    if any(marker in normalized_key for marker in SENSITIVE_MARKERS):
        return "[redacted]"
    if key == "target_author_profile":
        return _profile_summary(value)
    if key in WORK_LIST_KEYS and isinstance(value, list):
        return {"count": len(value), "sample": _work_sample(value)}
    if key == "source_works" and isinstance(value, dict):
        return {
            str(source): len(items) if isinstance(items, list) else 0
            for source, items in value.items()
        }
    if key in {"topic_clusters", "interest_timeline", "coauthors", "graph_nodes", "graph_edges"}:
        return {"count": len(value)} if isinstance(value, list) else {"count": 0}
    if key in {"agent_runs", "worker_outputs", "review_history", "profile_evidence", "analysis_claims"}:
        return {"count": len(value)} if isinstance(value, list) else {"count": 0}
    if key == "orchestrator_tasks" and isinstance(value, list):
        return [
            {
                "id": _safe_text(item.get("id"), 48),
                "kind": _safe_text(item.get("kind"), 48),
                "tier": _safe_text(item.get("tier"), 24),
            }
            for item in value
            if isinstance(item, dict)
        ]
    if key == "worker_task" and isinstance(value, dict):
        return {
            "id": _safe_text(value.get("id"), 48),
            "kind": _safe_text(value.get("kind"), 48),
            "tier": _safe_text(value.get("tier"), 24),
        }
    if key == "web_payload" and isinstance(value, dict):
        return {
            "name": _safe_text(value.get("name"), 80),
            "paper_count": len(value.get("papers") or []),
            "topic_count": len(value.get("topics") or value.get("researchDirections") or []),
            "coauthor_count": len(value.get("coauthors") or []),
            "has_agent_analysis": bool(value.get("agentAnalysis")),
        }
    if isinstance(value, list):
        return {"count": len(value)}
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for child_key, child_value in value.items():
            if any(marker in str(child_key).casefold() for marker in SENSITIVE_MARKERS):
                continue
            if isinstance(child_value, (str, int, float, bool)) or child_value is None:
                compact[str(child_key)] = (
                    _safe_text(child_value) if isinstance(child_value, str) else child_value
                )
            elif isinstance(child_value, list):
                compact[f"{child_key}_count"] = len(child_value)
            elif isinstance(child_value, dict):
                compact[f"{child_key}_keys"] = sorted(map(str, child_value.keys()))[:12]
        return compact
    if isinstance(value, str):
        return _safe_text(value)
    return value


def _state_summary(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {"type": type(state).__name__}
    keys = (
        "target_author_id",
        "target_author_ids",
        "target_author_profile",
        "raw_works",
        "deduped_works",
        "source_works",
        "adjudicated_works",
        "works_complete",
        "topic_clusters",
        "interest_timeline",
        "coauthors",
        "graph_nodes",
        "graph_edges",
        "orchestrator_tasks",
        "worker_task",
        "worker_outputs",
        "profile_evidence",
        "review_iteration",
        "review_history",
        "evidence_review",
        "warnings",
        "errors",
    )
    return {
        key: _compact_value(key, state[key])
        for key in keys
        if key in state and key not in {"openalex_api_key", "openalex_budget_provider"}
    }


def _result_summary(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"type": type(result).__name__, "value": _safe_text(result)}
    return {
        key: _compact_value(key, value)
        for key, value in result.items()
        if not any(marker in key.casefold() for marker in SENSITIVE_MARKERS)
    }


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def run(author_id: str, output: Path, budget_provider: str) -> dict[str, Any]:
    api_key = os.getenv("OPENALEX_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENALEX_API_KEY is not configured")

    state = default_state()
    state.update({
        "target_author_id": author_id,
        "target_author_ids": [author_id],
        "openalex_api_key": api_key,
        "openalex_budget_provider": budget_provider,
    })

    started_at = datetime.now().astimezone()
    started_monotonic = time.monotonic()
    active: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []

    for event in graph.stream(state, stream_mode="debug", version="v2"):
        data = event.get("data") or {}
        payload = data.get("payload") or {}
        event_type = data.get("type")
        task_id = str(payload.get("id") or "")
        event_time = _timestamp(data["timestamp"])
        if event_type == "task":
            active[task_id] = {
                "sequence": len(events) + len(active) + 1,
                "step": data.get("step"),
                "node": payload.get("name"),
                "started_at": event_time,
                "input": _state_summary(payload.get("input")),
            }
            continue
        if event_type != "task_result":
            continue

        record = active.pop(task_id, {
            "sequence": len(events) + 1,
            "step": data.get("step"),
            "node": payload.get("name"),
            "started_at": event_time,
            "input": {},
        })
        record["finished_at"] = event_time
        record["duration_seconds"] = round(
            max(0.0, (event_time - record["started_at"]).total_seconds()),
            3,
        )
        record["status"] = "failed" if payload.get("error") else "succeeded"
        record["error"] = _safe_text(payload.get("error"), 240)
        record["output"] = _result_summary(payload.get("result"))
        events.append(record)
        print(
            f"[{len(events):02d}] {record['node']} {record['status']} "
            f"{record['duration_seconds']:.3f}s",
            flush=True,
        )

    finished_at = datetime.now().astimezone()
    report = {
        "author_id": author_id,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "total_seconds": round(time.monotonic() - started_monotonic, 3),
        "events": events,
        "node_count": len(events),
        "failed_node_count": sum(event["status"] == "failed" for event in events),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report={output}", flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--author-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget-provider", default="workflow-transparency-test")
    args = parser.parse_args()
    run(args.author_id, args.output, args.budget_provider)


if __name__ == "__main__":
    main()
