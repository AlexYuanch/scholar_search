"""FastAPI application entry.

Endpoints:
  - GET /api/search?name=...  search scholars and return candidates
  - POST /api/profile         generate or read a cached scholar profile
  - POST /api/profile/stream  stream profile progress as NDJSON
"""
import asyncio
import json
import queue
import threading

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from nodes import dedup_authors
from openalex import search_authors
from state import default_state
from storage import ProfileStore
from workflow import graph


NODE_SIGNAL = {
    "resolve_author": "candidate_authors",
    "fetch_profile": "target_author_profile",
    "collect_works": "raw_works",
    "dedup_works": "deduped_works",
    "analyze_citations": "citation_summary",
    "agent_analyze_topics": "topic_clusters",
    "analyze_evolution": "interest_timeline",
    "analyze_coauthors": "coauthors",
    "build_graph": "graph_nodes",
    "generate_report": "profile_summary",
    "format_payload": "web_payload",
}

STAGE_LABELS = {
    "resolve_author": "搜索学者...",
    "fetch_profile": "获取基本信息...",
    "collect_works": "获取论文列表...",
    "dedup_works": "去重论文...",
    "analyze_citations": "统计引用数据...",
    "agent_analyze_topics": "AI 分析研究方向...",
    "analyze_evolution": "分析兴趣演化...",
    "analyze_coauthors": "分析合作关系...",
    "build_graph": "构建合作网络图...",
    "generate_report": "生成总结...",
    "format_payload": "组装数据...",
}

STAGE_ORDER = list(STAGE_LABELS.keys())

PROGRESS_ANCHORS = {
    "resolve_author": 5,
    "fetch_profile": 12,
    "collect_works": 35,
    "dedup_works": 42,
    "analyze_citations": 54,
    "agent_analyze_topics": 66,
    "analyze_evolution": 74,
    "analyze_coauthors": 83,
    "build_graph": 91,
    "generate_report": 97,
    "format_payload": 100,
}

PROGRESS_MESSAGES = {
    "resolve_author": ["确认已选择的学者身份..."],
    "fetch_profile": ["读取 OpenAlex 作者基础信息..."],
    "collect_works": [
        "正在分页获取 OpenAlex 论文列表...",
        "论文较多时会分批拉取，请稍候...",
    ],
    "dedup_works": ["正在按 DOI 与 OpenAlex ID 去重..."],
    "analyze_citations": [
        "正在按引用数计算 h-index...",
        "正在整理年度论文与引用趋势...",
    ],
    "agent_analyze_topics": [
        "正在扫描论文标题与主题标签...",
        "正在归纳研究方向和代表论文...",
    ],
    "analyze_evolution": ["正在按年份整理研究兴趣变化..."],
    "analyze_coauthors": ["正在统计合作作者与合作论文..."],
    "build_graph": ["正在构建合作网络节点和边..."],
    "generate_report": ["正在生成画像总结..."],
    "format_payload": ["正在组装前端展示数据..."],
}

profile_store = ProfileStore()
CACHE_MAX_AGE_DAYS = 7


def _cache_is_usable(cached: dict | None, refresh: bool) -> bool:
    return bool(cached and not refresh and profile_store.is_fresh(cached, CACHE_MAX_AGE_DAYS))


def _payload_with_defaults(author_id: str, payload: dict) -> dict:
    data = dict(payload)
    data.setdefault("authorId", author_id)
    data.setdefault("profileEvidence", [])
    return data


def _run_graph_stream(state, ev_q, result):
    """Run graph.stream in a thread and push completed stage events."""
    seen = set()
    final = None
    try:
        ev_q.put(("stage", "resolve_author"))
        for snap in graph.stream(state, stream_mode="values"):
            final = snap
            for node_name, signal_field in NODE_SIGNAL.items():
                if signal_field not in seen and snap.get(signal_field):
                    seen.add(signal_field)
                    ev_q.put(("stage", node_name))
                    break
        result.append(final or state)
        ev_q.put(("done", None))
    except Exception as exc:
        ev_q.put(("error", str(exc)))


app = FastAPI(title="Scholar Profile API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProfileRequest(BaseModel):
    author_id: str
    query_name: str = ""
    refresh: bool = False


@app.get("/api/search")
def search(name: str = Query(..., description="学者姓名")):
    """搜索学者姓名，返回去重后的候选人列表。"""
    candidates = search_authors(name)
    merged = dedup_authors(candidates)
    return {
        "candidates": [{
            "id": author["id"],
            "name": author["display_name"],
            "institution": (author.get("institutions") or [
                ((author.get("last_known_institutions") or [{}])[0].get("display_name", ""))
            ])[0],
            "institutions": author.get("institutions", []),
            "works_count": author.get("works_count", 0),
            "cited_by_count": author.get("cited_by_count", 0),
            "h_index": (author.get("summary_stats") or {}).get("h_index", 0),
            "merged_count": author.get("merged_count", 1),
            "merged_ids": author.get("merged_ids", [author.get("id", "")]),
            "disambiguation": author.get("disambiguation", ""),
        } for author in merged]
    }


@app.post("/api/profile")
def profile(req: ProfileRequest):
    """为选定的学者运行完整 LangGraph 工作流，返回画像数据。"""
    cached = profile_store.get_profile(req.author_id)
    if _cache_is_usable(cached, req.refresh):
        return {
            "status": "success",
            "source": "cache",
            "updated_at": cached["updated_at"],
            "warnings": cached["warnings"],
            "errors": cached["errors"],
            "data": _payload_with_defaults(req.author_id, cached["payload"]),
        }

    state = default_state()
    state["target_author_id"] = req.author_id
    state["query_name"] = req.query_name

    result = graph.invoke(state)
    payload = result.get("web_payload", {})
    warnings = result.get("warnings", [])
    errors = result.get("errors", [])
    profile_store.save_profile(
        req.author_id,
        req.query_name or payload.get("name", ""),
        payload,
        warnings,
        errors,
    )
    saved = profile_store.get_profile(req.author_id)

    return {
        "status": "success",
        "source": "live",
        "updated_at": saved["updated_at"] if saved else "",
        "warnings": warnings,
        "errors": errors,
        "data": payload,
    }


@app.get("/api/history")
def history(limit: int = Query(20, ge=1, le=100)):
    """返回最近生成过的学者画像历史。"""
    return {
        "items": [
            {
                "author_id": item["author_id"],
                "name": item["name"],
                "institution": item["institution"],
                "total_papers": item["total_papers"],
                "total_citations": item["total_citations"],
                "h_index": item["h_index"],
                "updated_at": item["updated_at"],
            }
            for item in profile_store.list_history(limit=limit)
        ]
    }


@app.post("/api/profile/stream")
async def profile_stream(req: ProfileRequest):
    """NDJSON 流式接口：逐步推送工作流进度，最后返回画像数据。"""
    cached = profile_store.get_profile(req.author_id)
    if _cache_is_usable(cached, req.refresh):
        async def cached_generate():
            yield json.dumps({"type": "init", "stages": STAGE_ORDER, "labels": STAGE_LABELS}) + "\n"
            yield json.dumps({
                "type": "progress",
                "progress": 100,
                "message": "已命中本地历史缓存，直接加载画像。",
            }, ensure_ascii=False) + "\n"
            yield json.dumps({
                "type": "cache_hit",
                "author_id": req.author_id,
                "updated_at": cached["updated_at"],
            }, ensure_ascii=False) + "\n"
            yield json.dumps({
                "type": "result",
                "source": "cache",
                "data": _payload_with_defaults(req.author_id, cached["payload"]),
            }, ensure_ascii=False) + "\n"

        return StreamingResponse(cached_generate(), media_type="application/x-ndjson")

    state = default_state()
    state["target_author_id"] = req.author_id
    state["query_name"] = req.query_name

    ev_q: "queue.Queue" = queue.Queue()
    result_holder: list = []

    async def generate():
        yield json.dumps({"type": "init", "stages": STAGE_ORDER, "labels": STAGE_LABELS}) + "\n"

        loop = asyncio.get_event_loop()
        thread = threading.Thread(target=_run_graph_stream, args=(state, ev_q, result_holder))
        thread.start()

        def poll():
            try:
                return ev_q.get(timeout=1.25)
            except queue.Empty:
                return ("progress", None)

        current_stage = STAGE_ORDER[0]
        progress = 1
        message_index = 0
        yield json.dumps({
            "type": "stage",
            "node": current_stage,
            "status": "running",
            "label": STAGE_LABELS[current_stage],
        }, ensure_ascii=False) + "\n"
        yield json.dumps({
            "type": "progress",
            "progress": progress,
            "message": PROGRESS_MESSAGES[current_stage][0],
            "node": current_stage,
        }, ensure_ascii=False) + "\n"

        while True:
            msg_type, data = await loop.run_in_executor(None, poll)
            if msg_type == "done":
                break
            if msg_type == "error":
                yield json.dumps({
                    "type": "error",
                    "message": data,
                    "node": current_stage,
                }, ensure_ascii=False) + "\n"
                thread.join()
                return
            if msg_type == "progress":
                target = PROGRESS_ANCHORS.get(current_stage, 99)
                if progress < target - 1:
                    progress += 1
                messages = PROGRESS_MESSAGES.get(current_stage, [STAGE_LABELS.get(current_stage, "")])
                message_index += 1
                yield json.dumps({
                    "type": "progress",
                    "progress": progress,
                    "message": messages[message_index % len(messages)],
                    "node": current_stage,
                }, ensure_ascii=False) + "\n"
                continue

            current_stage = data
            progress = max(progress, PROGRESS_ANCHORS.get(data, progress))
            yield json.dumps({
                "type": "stage",
                "node": data,
                "status": "completed",
                "label": STAGE_LABELS.get(data, data),
            }, ensure_ascii=False) + "\n"
            yield json.dumps({
                "type": "progress",
                "progress": progress,
                "message": f"{STAGE_LABELS.get(data, data).replace('...', '')}完成",
                "node": data,
            }, ensure_ascii=False) + "\n"

            current_index = STAGE_ORDER.index(data) if data in STAGE_ORDER else -1
            if current_index + 1 < len(STAGE_ORDER):
                current_stage = STAGE_ORDER[current_index + 1]
                message_index = 0
                yield json.dumps({
                    "type": "stage",
                    "node": current_stage,
                    "status": "running",
                    "label": STAGE_LABELS[current_stage],
                }, ensure_ascii=False) + "\n"

        thread.join()
        if not result_holder:
            yield json.dumps({
                "type": "error",
                "message": "画像生成失败，工作流未返回结果。",
                "node": current_stage,
            }, ensure_ascii=False) + "\n"
            return
        final_state = result_holder[0]
        payload = final_state.get("web_payload", {})
        warnings = final_state.get("warnings", [])
        errors = final_state.get("errors", [])
        profile_store.save_profile(
            req.author_id,
            req.query_name or payload.get("name", ""),
            payload,
            warnings,
            errors,
        )
        saved = profile_store.get_profile(req.author_id)
        yield json.dumps({
            "type": "progress",
            "progress": 100,
            "message": "画像生成完成，已写入本地历史缓存。",
        }, ensure_ascii=False) + "\n"
        yield json.dumps({
            "type": "result",
            "source": "live",
            "updated_at": saved["updated_at"] if saved else "",
            "data": payload,
        }, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/api/health")
def health():
    return {"status": "ok"}
