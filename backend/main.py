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
import math
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
    require_admin,
    require_super_admin,
    require_user,
    verify_password,
)
from credentials import (
    CredentialConfigurationError,
    CredentialDecryptionError,
    decrypt_secret,
    encrypt_secret,
    secret_hint,
    validate_credential_configuration,
)
from events import ProfileEventBroker
from openalex import (
    OpenAlexError,
    configure_budget_control,
    enrich_authors_for_disambiguation,
    search_authors,
    validate_openalex_api_key,
)
from quality import assess_profile_quality
from research_graph_repository import (
    enqueue_research_graph_refresh,
    get_research_graph,
    get_research_graph_object,
    get_research_graph_sync_state,
    research_graph_needs_refresh,
)
from repository import (
    AdminRoleError,
    APIQuotaExceeded,
    LoginRateLimitExceeded,
    RegistrationRateLimitExceeded,
    RepositoryNotConfigured,
    UsernameTaken,
    create_repository,
)
from search_service import (
    OPENALEX_MIN_REMAINING_CREDITS,
    SearchCoalesceTimeout,
    build_live_candidate_payload,
    search_with_cache,
)
from state import default_state
from workflow import graph


NODE_SIGNAL = {
    "fetch_profile": "target_author_profile",
    "collect_works": "raw_works",
    "dedup_works": "deduped_works",
    "collect_crossref": "source_audit",
    "adjudicate_sources": "data_audit",
    "plan_agents": "agent_plan",
    "analyze_citations": "citation_summary",
    "agent_analyze_topics": "topic_clusters",
    "analyze_evolution": "interest_timeline",
    "agent_analyze_trajectory": "trajectory_analysis",
    "analyze_coauthors": "coauthors",
    "build_graph": "graph_nodes",
    "generate_report": "profile_summary",
    "agent_review_report": "agent_review",
    "review_evidence": "evidence_review",
    "format_payload": "web_payload",
}

STAGE_LABELS = {
    "verify_identity": "核验身份",
    "aggregate_outputs": "聚合学术成果",
    "analyze_trajectory": "分析研究轨迹",
    "verify_evidence": "核验分析依据",
}

STAGE_ORDER = list(STAGE_LABELS.keys())

NODE_USER_STAGE = {
    "fetch_profile": "verify_identity",
    "collect_works": "aggregate_outputs",
    "dedup_works": "aggregate_outputs",
    "collect_crossref": "aggregate_outputs",
    "adjudicate_sources": "aggregate_outputs",
    "plan_agents": "analyze_trajectory",
    "analyze_citations": "aggregate_outputs",
    "agent_analyze_topics": "analyze_trajectory",
    "analyze_evolution": "analyze_trajectory",
    "agent_analyze_trajectory": "analyze_trajectory",
    "analyze_coauthors": "analyze_trajectory",
    "build_graph": "analyze_trajectory",
    "generate_report": "analyze_trajectory",
    "agent_review_report": "verify_evidence",
    "review_evidence": "verify_evidence",
    "format_payload": "verify_evidence",
}

PROGRESS_ANCHORS = {
    "fetch_profile": 6,
    "collect_works": 24,
    "dedup_works": 30,
    "collect_crossref": 42,
    "adjudicate_sources": 48,
    "plan_agents": 53,
    "analyze_citations": 59,
    "agent_analyze_topics": 67,
    "analyze_evolution": 73,
    "agent_analyze_trajectory": 79,
    "analyze_coauthors": 84,
    "build_graph": 89,
    "generate_report": 94,
    "agent_review_report": 97,
    "review_evidence": 98,
    "format_payload": 100,
}

PROGRESS_MESSAGES = {
    "fetch_profile": ["读取 OpenAlex 作者基础信息..."],
    "collect_works": [
        "正在分页获取 OpenAlex 论文列表...",
        "论文较多时会分批拉取，请稍候...",
    ],
    "dedup_works": ["正在按 DOI 与 OpenAlex ID 去重..."],
    "collect_crossref": [
        "正在通过 DOI 核验出版信息...",
        "论文较多时会分批核验，请稍候...",
    ],
    "adjudicate_sources": ["正在合并来源并记录数据差异..."],
    "plan_agents": ["正在根据数据复杂度规划分析 Agent..."],
    "analyze_citations": [
        "正在按引用数计算 h-index...",
        "正在整理年度论文与引用趋势...",
    ],
    "agent_analyze_topics": [
        "正在交叉分析论文主题、关键词与标题短语...",
        "正在过滤泛化学科标签并筛选代表作...",
    ],
    "analyze_evolution": ["正在按年份整理研究兴趣变化..."],
    "agent_analyze_trajectory": ["正在分析近期研究方向变化及其依据..."],
    "analyze_coauthors": ["正在统计合作作者与合作论文..."],
    "build_graph": ["正在构建合作网络节点和边..."],
    "generate_report": ["正在生成画像总结..."],
    "agent_review_report": ["正在由证据审查 Agent 复核分析结论..."],
    "review_evidence": ["正在检查结论是否可以回溯到论文依据..."],
    "format_payload": ["正在组装前端展示数据..."],
}

repository = create_repository()
event_broker = ProfileEventBroker(os.getenv("DATABASE_URL"))
CACHE_MAX_AGE_DAYS = 7
DUMMY_PASSWORD_HASH = hash_password("invalid-login-password")
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "600"))
SEARCH_RATE_LIMIT_PER_USER = int(os.getenv("SEARCH_RATE_LIMIT_PER_USER", "30"))
SEARCH_RATE_LIMIT_PER_IP = int(os.getenv("SEARCH_RATE_LIMIT_PER_IP", "120"))
PROFILE_RATE_LIMIT_PER_USER = int(os.getenv("PROFILE_RATE_LIMIT_PER_USER", "12"))
PROFILE_RATE_LIMIT_PER_IP = int(os.getenv("PROFILE_RATE_LIMIT_PER_IP", "60"))
ANALYTICS_COOKIE_NAME = "scholar_visitor"


def _openalex_budget_guard(provider: str) -> int | None:
    return repository.get_upstream_retry_after(
        provider,
        OPENALEX_MIN_REMAINING_CREDITS,
    )


def _openalex_budget_reporter(provider: str, snapshot: dict) -> None:
    repository.record_upstream_rate_limit(provider, **snapshot)


configure_budget_control(_openalex_budget_guard, _openalex_budget_reporter)


def _cache_is_fresh(cached: dict | None) -> bool:
    return bool(cached and repository.is_fresh(cached, CACHE_MAX_AGE_DAYS))


def _iso_datetime(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _payload_with_defaults(author_id: str, payload: dict, cached: dict | None = None) -> dict:
    data = dict(payload)
    data.setdefault("authorId", author_id)
    data.setdefault("profileEvidence", [])
    if cached:
        data.setdefault("scholarId", cached.get("scholar_id", ""))
        data.setdefault("profileVersion", cached.get("profile_version", 0))
        data.setdefault("refreshStatus", cached.get("refresh_status", "ready"))
        data.setdefault("updatedAt", cached.get("updated_at"))
    return data


def _build_live_search(
    repository_instance,
    query_text: str,
    *,
    api_key: str,
    budget_provider: str,
) -> tuple[list[dict], bool]:
    return build_live_candidate_payload(
        repository_instance,
        query_text,
        api_key=api_key,
        budget_provider=budget_provider,
        search_fn=lambda name: search_authors(
            name,
            api_key=api_key,
            budget_provider=budget_provider,
        ),
        enrich_fn=lambda candidates: enrich_authors_for_disambiguation(
            candidates,
            api_key=api_key,
            budget_provider=budget_provider,
        ),
    )


def _openalex_provider(user_id: str) -> str:
    return f"openalex:user:{user_id}"


def _require_openalex_credential(user: AuthUser) -> tuple[str, str]:
    server_api_key = os.getenv("OPENALEX_API_KEY", "").strip()
    if server_api_key:
        return server_api_key, "openalex:server"
    stored = repository.get_user_api_credential(user.id, "openalex")
    if not stored:
        raise HTTPException(
            status_code=503,
            detail="学术数据源尚未配置，请联系管理员。",
        )
    try:
        return decrypt_secret(stored["encrypted_secret"]), _openalex_provider(user.id)
    except (CredentialConfigurationError, CredentialDecryptionError) as exc:
        raise HTTPException(
            status_code=503,
            detail="服务器无法读取已保存的 OpenAlex API key，请联系管理员。",
        ) from exc


def _record_access(author_id: str, query_name: str, user: AuthUser | None) -> None:
    repository.touch_access(author_id)
    if user:
        repository.record_history(user.id, author_id, query_name)


def _auth_user_payload(user: AuthUser | dict) -> dict:
    role = str(user.role if isinstance(user, AuthUser) else user.get("role") or "user")
    return {
        "id": str(user.id if isinstance(user, AuthUser) else user["id"]),
        "username": str(
            user.username if isinstance(user, AuthUser) else user["username"]
        ),
        "role": role,
        "can_view_admin": role in {"admin", "super_admin"},
        "can_manage_admins": role == "super_admin",
    }


def _record_usage_event(
    request: Request,
    event_type: str,
    user: AuthUser | None = None,
    scholar_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    visitor_hash = getattr(request.state, "analytics_visitor_hash", None)
    if not visitor_hash:
        return
    repository.record_analytics_event(
        event_type,
        visitor_hash,
        user_id=user.id if user else None,
        scholar_id=scholar_id,
        metadata=metadata,
    )


def _consume_api_quota(action: str, user: AuthUser, request: Request) -> None:
    user_limit = SEARCH_RATE_LIMIT_PER_USER if action == "search" else PROFILE_RATE_LIMIT_PER_USER
    ip_limit = SEARCH_RATE_LIMIT_PER_IP if action == "search" else PROFILE_RATE_LIMIT_PER_IP
    try:
        repository.consume_api_quota(
            action,
            user.id,
            _client_ip(request),
            user_limit,
            ip_limit,
            RATE_LIMIT_WINDOW_SECONDS,
        )
    except APIQuotaExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="操作过于频繁，请稍后再试。",
            headers={"Retry-After": str(RATE_LIMIT_WINDOW_SECONDS)},
        ) from exc


def _openalex_rate_limit_detail(retry_after: str | None) -> str:
    try:
        seconds = max(1, int(retry_after or ""))
    except ValueError:
        return "OpenAlex 额度已用完，请在额度重置后重试。"
    if seconds >= 3600:
        wait = f"约 {math.ceil(seconds / 3600)} 小时"
    elif seconds >= 60:
        wait = f"约 {math.ceil(seconds / 60)} 分钟"
    else:
        wait = f"{seconds} 秒"
    return f"OpenAlex 额度已用完，{wait}后恢复。"


def _queue_stale_profile(author_id: str, cached: dict, user_id: str) -> str:
    if _cache_is_fresh(cached):
        return cached.get("refresh_status", "ready")
    repository.enqueue_refresh(
        author_id,
        reason="stale_access",
        requested_by_user_id=user_id,
    )
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


def _profile_status_event_key(event: dict) -> tuple[int, str, str]:
    return (
        int(event.get("version") or 0),
        str(event.get("status") or ""),
        str(event.get("updated_at") or ""),
    )


def _should_emit_profile_status(
    event: dict,
    requested_version: int,
    last_event_key: tuple[int, str, str] | None,
) -> bool:
    event_key = _profile_status_event_key(event)
    if event_key[0] < requested_version or event_key == last_event_key:
        return False
    return event_key[0] > requested_version or event_key[1] != "ready"


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
    if os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip():
        validate_credential_configuration()
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


@app.middleware("http")
async def record_analytics_activity(request: Request, call_next):
    excluded = (
        request.method == "OPTIONS"
        or request.url.path in {"/api/health", "/api/ready"}
    )
    if excluded:
        return await call_next(request)

    existing_visitor = request.cookies.get(ANALYTICS_COOKIE_NAME)
    if not existing_visitor and request.url.path != "/api/analytics/visit":
        return await call_next(request)

    raw_visitor = existing_visitor or generate_token()
    visitor_hash = hash_token(raw_visitor)
    request.state.analytics_visitor_hash = visitor_hash
    try:
        response = await call_next(request)
    except Exception:
        try:
            repository.touch_analytics_activity(visitor_hash, None)
            repository.record_analytics_event(
                "server_error",
                visitor_hash,
                metadata={"route": request.url.path[:200]},
            )
        except RepositoryNotConfigured:
            pass
        raise

    auth_user = getattr(request.state, "auth_user", None)
    try:
        repository.touch_analytics_activity(
            visitor_hash,
            auth_user.id if auth_user else None,
        )
        if response.status_code == 429:
            repository.record_analytics_event(
                "rate_limit",
                visitor_hash,
                user_id=auth_user.id if auth_user else None,
                metadata={"route": request.url.path[:200]},
            )
        elif response.status_code >= 500:
            event_type = (
                "source_failure"
                if request.url.path.startswith((
                    "/api/search",
                    "/api/profile",
                    "/api/authors/",
                ))
                else "server_error"
            )
            repository.record_analytics_event(
                event_type,
                visitor_hash,
                user_id=auth_user.id if auth_user else None,
                metadata={
                    "route": request.url.path[:200],
                    "status": response.status_code,
                },
            )
    except RepositoryNotConfigured:
        pass

    if not existing_visitor:
        response.set_cookie(
            key=ANALYTICS_COOKIE_NAME,
            value=raw_visitor,
            max_age=30 * 24 * 60 * 60,
            httponly=True,
            secure=_env_bool("COOKIE_SECURE", True),
            samesite="lax",
            path="/",
        )
    return response


@app.exception_handler(RepositoryNotConfigured)
def repository_not_configured(_request, exc: RepositoryNotConfigured):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


class ProfileRequest(BaseModel):
    author_id: str
    author_ids: list[str] = Field(default_factory=list, max_length=8)
    query_name: str = ""


def _requested_author_ids(req: ProfileRequest, cached: dict | None = None) -> list[str]:
    cached_ids = (
        (((cached or {}).get("payload") or {}).get("identityAudit") or {}).get("mergedAuthorIds")
        or []
    )
    return list(dict.fromkeys([req.author_id, *(req.author_ids or cached_ids)]))[:8]


class FavoriteRequest(BaseModel):
    author_id: str


class FavoriteSeenRequest(BaseModel):
    author_id: str
    profile_version: int = Field(ge=0)


class PasswordLoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)


class OpenAlexCredentialRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)


class ResearchGraphRefreshRequest(BaseModel):
    force_rebuild: bool = False


class AdminRoleRequest(BaseModel):
    role: str = Field(pattern="^(user|admin)$")


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


def _credential_transport_secure(request: Request) -> bool:
    if os.getenv("APP_ENV", "development").strip().casefold() != "production":
        return True
    hostname = (request.url.hostname or "").casefold()
    if hostname in {"localhost", "127.0.0.1", "::1", "testserver"}:
        return True
    forwarded_proto = (
        request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().casefold()
        if _env_bool("TRUST_PROXY_HEADERS")
        else ""
    )
    return (forwarded_proto or request.url.scheme).casefold() == "https"


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
    auth_user = AuthUser(
        id=str(user["id"]),
        username=str(user["username"]),
        role=str(user.get("role") or "user"),
    )
    request.state.auth_user = auth_user
    response = JSONResponse({
        "status": "success",
        "user": _auth_user_payload(auth_user),
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
    if req.username.strip().casefold() == "admin":
        raise HTTPException(status_code=409, detail="Username is reserved")
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
    response = _authenticated_response(user, request, status_code=201)
    _record_usage_event(request, "register_success", request.state.auth_user)
    return response


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
        _record_usage_event(request, "login_failed")
        raise HTTPException(status_code=401, detail="Invalid username or password")

    response = _authenticated_response(user, request)
    _record_usage_event(request, "login_success", request.state.auth_user)
    return response


@app.get("/api/auth/me")
def auth_me(user: AuthUser | None = Depends(optional_user)):
    return {
        "authenticated": user is not None,
        "user": _auth_user_payload(user) if user else None,
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


@app.post("/api/analytics/visit", status_code=204)
def analytics_visit(
    request: Request,
    user: AuthUser | None = Depends(optional_user),
):
    _record_usage_event(request, "page_view", user)
    return None


@app.get("/api/admin/dashboard")
def admin_dashboard(
    range_name: str = Query("7d", alias="range", pattern="^(24h|7d|30d)$"),
    _user: AuthUser = Depends(require_admin),
):
    return repository.get_admin_dashboard(range_name)


@app.get("/api/admin/users")
def admin_users(
    query: str = Query("", max_length=64),
    cursor: str | None = None,
    _user: AuthUser = Depends(require_super_admin),
):
    offset = _decode_cursor(cursor)
    result = repository.list_admin_users(query=query, limit=50, offset=offset)
    next_offset = offset + len(result["items"])
    return {
        "items": result["items"],
        "total": result["total"],
        "next_cursor": (
            _encode_cursor(next_offset)
            if next_offset < result["total"]
            else None
        ),
    }


@app.patch("/api/admin/users/{user_id}/role")
def update_admin_role(
    user_id: UUID,
    req: AdminRoleRequest,
    _user: AuthUser = Depends(require_super_admin),
):
    try:
        return repository.set_user_role(str(user_id), req.role)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc
    except AdminRoleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/settings/openalex")
def openalex_settings(user: AuthUser = Depends(require_user)):
    stored = repository.get_user_api_credential(user.id, "openalex")
    return {
        "configured": stored is not None,
        "key_hint": stored.get("key_hint") if stored else None,
        "validated_at": _iso_datetime(stored.get("validated_at")) if stored else None,
        "updated_at": _iso_datetime(stored.get("updated_at")) if stored else None,
    }


@app.put("/api/settings/openalex")
def save_openalex_settings(
    req: OpenAlexCredentialRequest,
    request: Request,
    user: AuthUser = Depends(require_user),
):
    if not _credential_transport_secure(request):
        raise HTTPException(
            status_code=426,
            detail="生产环境必须使用 HTTPS 才能提交 OpenAlex API key。",
        )
    api_key = req.api_key.strip()
    provider = _openalex_provider(user.id)
    try:
        usage = validate_openalex_api_key(api_key, budget_provider=provider)
        stored = repository.save_user_api_credential(
            user.id,
            "openalex",
            encrypt_secret(api_key),
            secret_hint(api_key),
        )
    except OpenAlexError as exc:
        if exc.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="OpenAlex 暂时限流，尚未保存，请稍后重试。",
                headers={"Retry-After": exc.retry_after or "60"},
            ) from exc
        raise HTTPException(
            status_code=400,
            detail="OpenAlex API key 无效或当前无法验证，尚未保存。",
        ) from exc
    except CredentialConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail="服务器尚未配置凭据加密，无法保存 API key。",
        ) from exc
    return {
        "configured": True,
        "key_hint": stored["key_hint"],
        "validated_at": _iso_datetime(stored["validated_at"]),
        "updated_at": _iso_datetime(stored["updated_at"]),
        "usage": usage,
    }


@app.delete("/api/settings/openalex")
def delete_openalex_settings(user: AuthUser = Depends(require_user)):
    repository.delete_user_api_credential(user.id, "openalex")
    return {"status": "success", "configured": False}


@app.get("/api/search")
def search(
    request: Request,
    name: str = Query(..., description="学者姓名"),
    user: AuthUser = Depends(require_user),
):
    """搜索学者姓名，返回去重后的候选人列表。"""
    api_key, budget_provider = _require_openalex_credential(user)
    _consume_api_quota("search", user, request)
    _record_usage_event(request, "search", user)
    try:
        return search_with_cache(
            repository,
            name,
            builder=lambda repo, query: _build_live_search(
                repo,
                query,
                api_key=api_key,
                budget_provider=budget_provider,
            ),
            budget_provider=budget_provider,
            requested_by_user_id=user.id,
        )
    except OpenAlexError as exc:
        if exc.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail=_openalex_rate_limit_detail(exc.retry_after),
                headers={"Retry-After": exc.retry_after or "60"},
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="学术数据源暂时不可用，请稍后重试。",
        ) from exc
    except SearchCoalesceTimeout as exc:
        raise HTTPException(
            status_code=503,
            detail="该姓名正在由其他请求核验，请稍后重试。",
            headers={"Retry-After": "3"},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/profile")
def profile(req: ProfileRequest, request: Request, user: AuthUser = Depends(require_user)):
    """返回最新画像；过期画像立即返回并在后台排队更新。"""
    cached = repository.get_profile(req.author_id)
    if cached:
        refresh_status = _queue_stale_profile(req.author_id, cached, user.id)
        _record_access(req.author_id, req.query_name or cached.get("query_name", ""), user)
        data = _payload_with_defaults(req.author_id, cached["payload"], cached)
        data["refreshStatus"] = refresh_status
        _record_usage_event(
            request,
            "profile_view",
            user,
            scholar_id=cached.get("scholar_id"),
        )
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

    api_key, budget_provider = _require_openalex_credential(user)
    state = default_state()
    state["target_author_id"] = req.author_id
    state["target_author_ids"] = _requested_author_ids(req, cached)
    state["openalex_api_key"] = api_key
    state["openalex_budget_provider"] = budget_provider
    _consume_api_quota("profile", user, request)

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
    _record_usage_event(
        request,
        "profile_view",
        user,
        scholar_id=saved.get("scholar_id"),
    )

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
@app.get("/api/tracking")
def favorites(user: AuthUser = Depends(require_user)):
    return {"items": repository.list_favorites(user.id)}


@app.post("/api/favorites")
@app.post("/api/tracking")
def add_favorite(req: FavoriteRequest, user: AuthUser = Depends(require_user)):
    try:
        return repository.add_favorite(user.id, req.author_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Scholar profile not found") from exc


@app.post("/api/favorites/seen")
@app.post("/api/tracking/seen")
def mark_favorite_seen(req: FavoriteSeenRequest, user: AuthUser = Depends(require_user)):
    repository.mark_favorite_seen(user.id, req.author_id, req.profile_version)
    return {"status": "success"}


@app.delete("/api/favorites/{author_id:path}")
@app.delete("/api/tracking/{author_id:path}")
def remove_favorite(author_id: str, user: AuthUser = Depends(require_user)):
    repository.remove_favorite(user.id, author_id)
    return {"status": "success"}


@app.post("/api/tracking/{author_id:path}/refresh")
def refresh_tracking(author_id: str, user: AuthUser = Depends(require_user)):
    """Queue a tracked scholar refresh without running the workflow in the Web process."""
    if not repository.is_tracking(user.id, author_id):
        raise HTTPException(status_code=404, detail="Research tracking not found")
    _require_openalex_credential(user)
    try:
        job_id = repository.enqueue_refresh(
            author_id,
            reason="manual_tracking",
            requested_by_user_id=user.id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Scholar profile not found") from exc
    cached = repository.get_profile(author_id) or {}
    return {
        "status": cached.get("refresh_status", "queued"),
        "job_id": job_id,
    }


@app.post("/api/authors/{author_id:path}/profile/refresh")
def refresh_profile(
    author_id: str,
    request: Request,
    user: AuthUser = Depends(require_user),
):
    """Queue a complete profile workflow while keeping the current profile available."""
    cached = repository.get_profile(author_id)
    if not cached:
        raise HTTPException(status_code=404, detail="Scholar profile not found")
    if cached.get("refresh_status") not in {"queued", "updating"}:
        _consume_api_quota("profile", user, request)
        _require_openalex_credential(user)
    try:
        job_id = repository.enqueue_refresh(
            author_id,
            reason="manual_profile",
            requested_by_user_id=user.id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Scholar profile not found") from exc
    latest = repository.get_profile(author_id) or cached
    _record_usage_event(
        request,
        "profile_refresh",
        user,
        scholar_id=cached.get("scholar_id"),
    )
    return {
        "status": latest.get("refresh_status", "queued"),
        "job_id": job_id,
        "profile_version": int(cached.get("profile_version") or 0),
    }


@app.get("/api/authors/{author_id:path}/works")
def author_works(
    author_id: str,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    sort: str = Query("citations", pattern="^(citations|year)$"),
    year: int | None = Query(None, ge=1800, le=2100),
    topic: str | None = Query(None, min_length=1, max_length=200),
    _user: AuthUser = Depends(require_user),
):
    offset = _decode_cursor(cursor)
    page = repository.list_works(
        author_id,
        limit=limit,
        offset=offset,
        sort=sort,
        year=year,
        topic=topic.strip() if topic else None,
    )
    next_offset = offset + len(page["items"])
    return {
        "items": page["items"],
        "total": page["total"],
        "next_cursor": _encode_cursor(next_offset) if next_offset < page["total"] else None,
    }


@app.get("/api/authors/{author_id:path}/research-graph")
def author_research_graph(
    author_id: str,
    request: Request,
    user: AuthUser = Depends(require_user),
):
    """Return a scholar graph and lazily queue it only when the tab is opened."""
    state = get_research_graph_sync_state(repository, author_id) or {}
    if state.get("status") != "failed" and research_graph_needs_refresh(
        repository,
        author_id,
    ):
        _consume_api_quota("profile", user, request)
        _require_openalex_credential(user)
        try:
            enqueue_research_graph_refresh(
                repository,
                author_id,
                requested_by_user_id=user.id,
                reason="graph_view",
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Scholar profile not found",
            ) from exc
    return get_research_graph(repository, author_id)


@app.post("/api/authors/{author_id:path}/research-graph/refresh")
def refresh_author_research_graph(
    author_id: str,
    req: ResearchGraphRefreshRequest,
    request: Request,
    user: AuthUser = Depends(require_user),
):
    """Queue an incremental update or an explicit one-scholar rebuild."""
    state = get_research_graph_sync_state(repository, author_id) or {}
    status = state.get("status", "never")
    if status in {"queued", "updating"}:
        return {
            "status": status,
            "job_id": None,
            "force_rebuild": bool(req.force_rebuild),
        }
    if req.force_rebuild and status != "failed":
        raise HTTPException(
            status_code=409,
            detail="只有图谱更新失败后才需要完整重建。",
        )
    if (
        status == "ready"
        and not req.force_rebuild
        and not research_graph_needs_refresh(repository, author_id)
    ):
        return {
            "status": "ready",
            "job_id": None,
            "force_rebuild": False,
        }
    _consume_api_quota("profile", user, request)
    _require_openalex_credential(user)
    try:
        job_id = enqueue_research_graph_refresh(
            repository,
            author_id,
            requested_by_user_id=user.id,
            reason="manual_rebuild" if req.force_rebuild else "manual_refresh",
            force_rebuild=req.force_rebuild,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Scholar profile not found") from exc
    return {
        "status": "queued",
        "job_id": job_id,
        "force_rebuild": req.force_rebuild,
    }


@app.get("/api/research-graph/objects/{object_type}/{object_id}")
def research_graph_object(
    object_type: str,
    object_id: UUID,
    _user: AuthUser = Depends(require_user),
):
    """Return details for a clicked author, paper, institution, or topic."""
    item = get_research_graph_object(repository, object_type, str(object_id))
    if not item:
        raise HTTPException(status_code=404, detail="Research graph object not found")
    return item


@app.post("/api/profile/stream")
async def profile_stream(
    req: ProfileRequest,
    request: Request,
    user: AuthUser = Depends(require_user),
):
    """NDJSON 流式接口：逐步推送工作流进度，最后返回画像数据。"""
    _consume_api_quota("profile", user, request)
    cached = await asyncio.to_thread(repository.get_profile, req.author_id)
    if cached:
        refresh_status = await asyncio.to_thread(
            _queue_stale_profile,
            req.author_id,
            cached,
            user.id,
        )
        await asyncio.to_thread(
            _record_access,
            req.author_id,
            req.query_name or cached.get("query_name", ""),
            user,
        )
        await asyncio.to_thread(
            _record_usage_event,
            request,
            "profile_view",
            user,
            cached.get("scholar_id"),
        )

        async def generate_cached():
            yield json.dumps({
                "type": "init",
                "stages": STAGE_ORDER,
                "labels": STAGE_LABELS,
            }, ensure_ascii=False) + "\n"
            yield json.dumps({
                "type": "result",
                "source": "cache",
                "updated_at": cached["updated_at"],
                "profile_version": cached.get("profile_version", 0),
                "refresh_status": refresh_status,
                "data": _payload_with_defaults(req.author_id, cached["payload"], cached) | {
                    "refreshStatus": refresh_status,
                },
            }, ensure_ascii=False) + "\n"

        return StreamingResponse(generate_cached(), media_type="application/x-ndjson")

    api_key, budget_provider = _require_openalex_credential(user)
    state = default_state()
    state["target_author_id"] = req.author_id
    state["target_author_ids"] = _requested_author_ids(req, cached)
    state["openalex_api_key"] = api_key
    state["openalex_budget_provider"] = budget_provider

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
        current_node = "fetch_profile"
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
            "message": PROGRESS_MESSAGES[current_node][0],
            "message_code": current_node,
            "node": current_stage,
        }, ensure_ascii=False) + "\n"

        while True:
            msg_type, data = await loop.run_in_executor(None, poll)
            if msg_type == "done":
                break
            if msg_type == "error":
                lowered = str(data).casefold()
                error_code = (
                    "rate_limit" if "429" in lowered or "rate limit" in lowered
                    else "timeout" if "timeout" in lowered or "timed out" in lowered
                    else "network_error" if "connection" in lowered or "network" in lowered
                    else "worker_failed"
                )
                yield json.dumps({
                    "type": "error",
                    "message": data,
                    "code": error_code,
                    "node": current_stage,
                }, ensure_ascii=False) + "\n"
                thread.join()
                return
            if msg_type == "progress":
                target = PROGRESS_ANCHORS.get(current_node, 99)
                if progress < target - 1:
                    progress += 1
                messages = PROGRESS_MESSAGES.get(current_node, [STAGE_LABELS.get(current_stage, "")])
                message_index += 1
                yield json.dumps({
                    "type": "progress",
                    "progress": progress,
                    "message": messages[message_index % len(messages)],
                    "message_code": current_node,
                    "node": current_stage,
                }, ensure_ascii=False) + "\n"
                continue

            current_node = data
            next_stage = NODE_USER_STAGE.get(data, current_stage)
            progress = max(progress, PROGRESS_ANCHORS.get(data, progress))
            if next_stage != current_stage:
                yield json.dumps({
                    "type": "stage",
                    "node": current_stage,
                    "status": "completed",
                    "label": STAGE_LABELS[current_stage],
                }, ensure_ascii=False) + "\n"
                current_stage = next_stage
                yield json.dumps({
                    "type": "stage",
                    "node": current_stage,
                    "status": "running",
                    "label": STAGE_LABELS[current_stage],
                }, ensure_ascii=False) + "\n"
            yield json.dumps({
                "type": "progress",
                "progress": progress,
                "message": PROGRESS_MESSAGES.get(data, [STAGE_LABELS[current_stage]])[0],
                "message_code": data,
                "node": current_stage,
            }, ensure_ascii=False) + "\n"
            message_index = 0

        thread.join()
        if not result_holder:
            yield json.dumps({
                "type": "error",
                "message": "画像生成失败，工作流未返回结果。",
                "node": current_stage,
            }, ensure_ascii=False) + "\n"
            return
        final_state = result_holder[0]
        assessment = assess_profile_quality(final_state, cached)
        if not assessment.publishable:
            yield json.dumps({
                "type": "error",
                "message": "本次获取的数据不完整，请稍后重试。",
                "quality_flags": assessment.flags,
                "node": current_stage,
            }, ensure_ascii=False) + "\n"
            return
        yield json.dumps({
            "type": "stage",
            "node": current_stage,
            "status": "completed",
            "label": STAGE_LABELS[current_stage],
        }, ensure_ascii=False) + "\n"
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
        await asyncio.to_thread(
            _record_usage_event,
            request,
            "profile_view",
            user,
            saved.get("scholar_id"),
        )
        yield json.dumps({
            "type": "progress",
            "progress": 100,
            "message": "已获取当前最新学者信息。",
            "message_code": "complete",
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
        last_event_key: tuple[int, str, str] | None = None
        subscriber = broker.subscribe(scholar_key)
        try:
            current = await asyncio.to_thread(repository.get_profile_status, scholar_key)
            if current:
                last_event_key = _profile_status_event_key(current)
                if _should_emit_profile_status(current, version, None):
                    yield f"event: profile\ndata: {json.dumps(current, ensure_ascii=False)}\n\n"

            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(subscriber.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if not _should_emit_profile_status(event, version, last_event_key):
                    continue
                last_event_key = _profile_status_event_key(event)
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
