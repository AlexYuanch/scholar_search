"""FastAPI application entry.

Endpoints:
  - GET /api/search?name=...  search scholars and return candidates
  - POST /api/profile         generate or read a cached scholar profile
  - POST /api/profile/stream  stream profile progress as NDJSON
"""
import asyncio
import base64
import ipaddress
import json
import os
import queue
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from auth import (
    SESSION_COOKIE_NAME,
    AuthUser,
    generate_token,
    hash_password,
    hash_token,
    optional_user,
    require_user,
    verify_password,
)
from events import ProfileEventBroker
from nodes import dedup_authors
from openalex import search_authors
from quality import assess_profile_quality
from repository import (
    LoginRateLimitExceeded,
    RegistrationRateLimitExceeded,
    RepositoryNotConfigured,
    UsernameTaken,
    create_repository,
)
from state import default_state
from workflow import graph


NODE_SIGNAL = {
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
    "fetch_profile": 8,
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

repository = create_repository()
event_broker = ProfileEventBroker(os.getenv("DATABASE_URL"))
CACHE_MAX_AGE_DAYS = 7
DUMMY_PASSWORD_HASH = hash_password("invalid-login-password")


def _cache_is_fresh(cached: dict | None) -> bool:
    return bool(cached and repository.is_fresh(cached, CACHE_MAX_AGE_DAYS))


def _payload_with_defaults(author_id: str, payload: dict, cached: dict | None = None) -> dict:
    data = dict(payload)
    data.setdefault("authorId", author_id)
    data.setdefault("profileEvidence", [])
    if cached:
        data.setdefault("scholarId", cached.get("scholar_id", ""))
        data.setdefault("profileVersion", cached.get("profile_version", 0))
        data.setdefault("refreshStatus", cached.get("refresh_status", "ready"))
    return data


def _record_access(author_id: str, query_name: str, user: AuthUser | None) -> None:
    repository.touch_access(author_id)
    if user:
        repository.record_history(user.id, author_id, query_name)


def _queue_stale_profile(author_id: str, cached: dict) -> str:
    if _cache_is_fresh(cached):
        return cached.get("refresh_status", "ready")
    repository.enqueue_refresh(author_id, reason="stale_access")
    return "queued"


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return max(0, int(base64.urlsafe_b64decode(padded).decode()))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


def _run_graph_stream(state, ev_q, result):
    """Run graph.stream in a thread and push completed stage events."""
    seen = set()
    final = None
    try:
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


@asynccontextmanager
async def lifespan(application: FastAPI):
    event_broker.start()
    yield
    event_broker.stop()


app = FastAPI(title="Scholar Profile API", version="0.2.0", lifespan=lifespan)
app.state.repository = repository
app.state.event_broker = event_broker

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RepositoryNotConfigured)
def repository_not_configured(_request, exc: RepositoryNotConfigured):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


class ProfileRequest(BaseModel):
    author_id: str
    query_name: str = ""


class FavoriteRequest(BaseModel):
    author_id: str


class PasswordLoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _client_ip(request: Request) -> str | None:
    if _env_bool("TRUST_PROXY_HEADERS"):
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            try:
                return str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass
    return request.client.host if request.client else None


def _authenticated_response(user: dict, request: Request, status_code: int = 200) -> JSONResponse:
    raw_session = generate_token()
    session_ttl_days = int(os.getenv("SESSION_TTL_DAYS", "30"))
    repository.create_user_session(
        user_id=user["id"],
        session_hash=hash_token(raw_session),
        session_expires_at=datetime.now(timezone.utc) + timedelta(days=session_ttl_days),
        user_agent=request.headers.get("user-agent", ""),
        request_ip=_client_ip(request),
    )
    response = JSONResponse({
        "status": "success",
        "user": {"id": str(user["id"]), "username": user["username"]},
    }, status_code=status_code)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_session,
        max_age=session_ttl_days * 24 * 60 * 60,
        httponly=True,
        secure=_env_bool("COOKIE_SECURE", True),
        samesite="lax",
        path="/",
    )
    return response


@app.post("/api/auth/register")
def auth_register(req: PasswordLoginRequest, request: Request):
    request_ip = _client_ip(request)
    try:
        repository.enforce_registration_rate_limit(request_ip)
    except RegistrationRateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail="Too many registration attempts") from exc

    try:
        user = repository.create_password_user(req.username, hash_password(req.password))
    except UsernameTaken as exc:
        repository.record_registration_attempt(request_ip, False)
        raise HTTPException(status_code=409, detail="Username is already registered") from exc

    repository.record_registration_attempt(request_ip, True)
    return _authenticated_response(user, request, status_code=201)


@app.post("/api/auth/login")
def auth_login(req: PasswordLoginRequest, request: Request):
    username = req.username.strip()
    request_ip = _client_ip(request)
    try:
        repository.enforce_login_rate_limit(username, request_ip)
    except LoginRateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail="Too many failed login attempts") from exc

    user = repository.get_user_for_login(username)
    password_hash = user["password_hash"] if user else DUMMY_PASSWORD_HASH
    valid_credentials = verify_password(req.password, password_hash)
    authenticated = bool(user and user.get("is_active") and valid_credentials)
    repository.record_login_attempt(username, request_ip, authenticated)
    if not authenticated:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    return _authenticated_response(user, request)


@app.get("/api/auth/me")
def auth_me(user: AuthUser | None = Depends(optional_user)):
    return {
        "authenticated": user is not None,
        "user": {"id": user.id, "username": user.username} if user else None,
    }


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        repository.revoke_session(hash_token(session_token))
    response = JSONResponse({"status": "success"})
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=_env_bool("COOKIE_SECURE", True),
        samesite="lax",
    )
    return response


@app.get("/api/search")
def search(
    name: str = Query(..., description="学者姓名"),
    _user: AuthUser = Depends(require_user),
):
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
            "orcid": author.get("orcid"),
            "merged_count": author.get("merged_count", 1),
            "merged_ids": author.get("merged_ids", [author.get("id", "")]),
            "disambiguation": author.get("disambiguation", ""),
        } for author in merged]
    }


@app.post("/api/profile")
def profile(req: ProfileRequest, user: AuthUser = Depends(require_user)):
    """返回最新画像；过期画像立即返回并在后台排队更新。"""
    cached = repository.get_profile(req.author_id)
    if cached:
        refresh_status = _queue_stale_profile(req.author_id, cached)
        _record_access(req.author_id, req.query_name or cached.get("query_name", ""), user)
        data = _payload_with_defaults(req.author_id, cached["payload"], cached)
        data["refreshStatus"] = refresh_status
        return {
            "status": "success",
            "source": "cache",
            "updated_at": cached["updated_at"],
            "scholar_id": cached.get("scholar_id", ""),
            "profile_version": cached.get("profile_version", 0),
            "refresh_status": refresh_status,
            "warnings": cached["warnings"],
            "errors": cached["errors"],
            "data": data,
        }

    state = default_state()
    state["target_author_id"] = req.author_id

    result = graph.invoke(state)
    assessment = assess_profile_quality(result)
    if not assessment.publishable:
        raise HTTPException(status_code=502, detail={"quality_flags": assessment.flags})
    saved = repository.publish_profile(
        result,
        query_name=req.query_name or (result.get("web_payload") or {}).get("name", ""),
        quality_flags=assessment.flags,
    )
    _record_access(req.author_id, req.query_name or saved.get("query_name", ""), user)

    return {
        "status": "success",
        "source": "live",
        "updated_at": saved["updated_at"],
        "scholar_id": saved.get("scholar_id", ""),
        "profile_version": saved.get("profile_version", 0),
        "refresh_status": "ready",
        "warnings": saved["warnings"],
        "errors": saved["errors"],
        "data": _payload_with_defaults(req.author_id, saved["payload"], saved),
    }


@app.get("/api/history")
def history(
    limit: int = Query(20, ge=1, le=100),
    user: AuthUser = Depends(require_user),
):
    """返回当前登录用户的私有查询历史。"""
    return {"items": repository.list_history(user.id, limit=limit)}


@app.get("/api/favorites")
def favorites(user: AuthUser = Depends(require_user)):
    return {"items": repository.list_favorites(user.id)}


@app.post("/api/favorites")
def add_favorite(req: FavoriteRequest, user: AuthUser = Depends(require_user)):
    try:
        return repository.add_favorite(user.id, req.author_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Scholar profile not found") from exc


@app.delete("/api/favorites/{author_id:path}")
def remove_favorite(author_id: str, user: AuthUser = Depends(require_user)):
    repository.remove_favorite(user.id, author_id)
    return {"status": "success"}


@app.get("/api/authors/{author_id:path}/works")
def author_works(
    author_id: str,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    sort: str = Query("citations", pattern="^(citations|year)$"),
    _user: AuthUser = Depends(require_user),
):
    offset = _decode_cursor(cursor)
    page = repository.list_works(author_id, limit=limit, offset=offset, sort=sort)
    next_offset = offset + len(page["items"])
    return {
        "items": page["items"],
        "total": page["total"],
        "next_cursor": _encode_cursor(next_offset) if next_offset < page["total"] else None,
    }


@app.post("/api/profile/stream")
async def profile_stream(
    req: ProfileRequest,
    user: AuthUser = Depends(require_user),
):
    """NDJSON 流式接口：逐步推送工作流进度，最后返回画像数据。"""
    cached = await asyncio.to_thread(repository.get_profile, req.author_id)
    if cached:
        refresh_status = await asyncio.to_thread(_queue_stale_profile, req.author_id, cached)
        await asyncio.to_thread(
            _record_access,
            req.author_id,
            req.query_name or cached.get("query_name", ""),
            user,
        )

        async def cached_generate():
            yield json.dumps({"type": "init", "stages": STAGE_ORDER, "labels": STAGE_LABELS}) + "\n"
            yield json.dumps({
                "type": "progress",
                "progress": 100,
                "message": "已加载最新画像。" if refresh_status == "ready" else "已加载当前画像，后台正在更新。",
            }, ensure_ascii=False) + "\n"
            yield json.dumps({
                "type": "cache_hit",
                "author_id": req.author_id,
                "updated_at": cached["updated_at"],
                "refresh_status": refresh_status,
            }, ensure_ascii=False) + "\n"
            data = _payload_with_defaults(req.author_id, cached["payload"], cached)
            data["refreshStatus"] = refresh_status
            yield json.dumps({
                "type": "result",
                "source": "cache",
                "updated_at": cached["updated_at"],
                "profile_version": cached.get("profile_version", 0),
                "refresh_status": refresh_status,
                "data": data,
            }, ensure_ascii=False) + "\n"

        return StreamingResponse(cached_generate(), media_type="application/x-ndjson")

    state = default_state()
    state["target_author_id"] = req.author_id

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
        assessment = assess_profile_quality(final_state)
        if not assessment.publishable:
            yield json.dumps({
                "type": "error",
                "message": "画像数据未通过完整性检查，未发布到最新画像。",
                "quality_flags": assessment.flags,
                "node": current_stage,
            }, ensure_ascii=False) + "\n"
            return
        saved = await asyncio.to_thread(
            repository.publish_profile,
            final_state,
            req.query_name or (final_state.get("web_payload") or {}).get("name", ""),
            assessment.flags,
        )
        await asyncio.to_thread(
            _record_access,
            req.author_id,
            req.query_name or saved.get("query_name", ""),
            user,
        )
        yield json.dumps({
            "type": "progress",
            "progress": 100,
            "message": "画像生成完成，已发布为最新版本。",
        }, ensure_ascii=False) + "\n"
        yield json.dumps({
            "type": "result",
            "source": "live",
            "updated_at": saved["updated_at"],
            "profile_version": saved.get("profile_version", 0),
            "refresh_status": "ready",
            "data": _payload_with_defaults(req.author_id, saved["payload"], saved),
        }, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/api/profiles/{scholar_id}/events")
async def profile_events(
    scholar_id: UUID,
    request: Request,
    version: int = Query(0, ge=0),
    _user: AuthUser = Depends(require_user),
):
    """Stream lightweight profile status changes over server-sent events."""
    broker: ProfileEventBroker = request.app.state.event_broker
    if not broker.configured:
        raise HTTPException(status_code=503, detail="Profile events are not configured")

    scholar_key = str(scholar_id)

    async def generate():
        latest_version = version
        subscriber = broker.subscribe(scholar_key)
        try:
            current = await asyncio.to_thread(repository.get_profile_status, scholar_key)
            if current and int(current["version"]) > latest_version:
                latest_version = int(current["version"])
                yield f"event: profile\ndata: {json.dumps(current, ensure_ascii=False)}\n\n"

            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(subscriber.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                event_version = int(event.get("version", 0))
                if event_version <= latest_version:
                    continue
                latest_version = event_version
                yield f"event: profile\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            broker.unsubscribe(scholar_key, subscriber)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/ready")
def ready():
    if not repository.healthcheck():
        raise HTTPException(status_code=503, detail="Database is not ready")
    return {"status": "ready"}
