"""Background worker that refreshes due scholar profiles."""
from __future__ import annotations

import logging
import os
import time

from credentials import (
    CredentialConfigurationError,
    CredentialDecryptionError,
    decrypt_secret,
)
from field_discovery import (
    advance_discoveries_for_candidate,
    claim_field_discovery,
    fail_field_discovery,
    maintain_field_discovery_jobs,
    process_claimed_field_discovery,
)
from openalex import configure_budget_control
from quality import assess_profile_quality
from research_graph import IncompleteGraphSync, sync_scholar_research_graph
from research_graph_repository import (
    claim_research_graph_refresh,
    complete_research_graph_refresh,
    fail_research_graph_refresh,
    maintain_research_graph_jobs,
)
from repository import create_repository
from search_service import (
    OPENALEX_MIN_REMAINING_CREDITS,
    build_live_candidate_payload,
    run_claimed_search_job,
)
from state import default_state
from workflow import graph


logger = logging.getLogger(__name__)


class MissingJobCredential(RuntimeError):
    pass


def process_one_search_job(
    repository,
    builder=None,
) -> bool:
    job = repository.claim_openalex_search_job()
    if not job:
        return False
    if builder is None:
        try:
            api_key, budget_provider = _job_openalex_credential(repository, job)
        except MissingJobCredential as exc:
            repository.fail_openalex_search_job(str(job["id"]), str(exc), retry=False)
            return False
        builder = lambda repo, query: build_live_candidate_payload(
            repo,
            query,
            api_key=api_key,
            budget_provider=budget_provider,
        )
    try:
        run_claimed_search_job(repository, job, builder)
        return True
    except Exception:
        return False


def process_one_job(repository, workflow_graph=graph) -> bool:
    job = repository.claim_refresh_job()
    if not job:
        return False

    job_id = str(job["id"])
    author_id = job["author_id"]
    cached = repository.get_profile(author_id)
    try:
        if job.get("requested_by_user_id"):
            api_key, budget_provider = _job_openalex_credential(repository, job)
        elif workflow_graph is graph:
            raise MissingJobCredential("Refresh job has no requesting user")
        else:
            api_key, budget_provider = "", ""
        state = default_state()
        state["target_author_id"] = author_id
        state["openalex_api_key"] = api_key
        state["openalex_budget_provider"] = budget_provider
        state["target_author_ids"] = list(dict.fromkeys([
            author_id,
            *(
                ((((cached or {}).get("payload") or {}).get("identityAudit") or {}).get("mergedAuthorIds"))
                or []
            ),
        ]))[:8]
        result = workflow_graph.invoke(state)
        assessment = assess_profile_quality(result, cached=cached)
        if not assessment.publishable:
            retry = int(job.get("attempts", 1)) < 3
            repository.fail_refresh_job(job_id, ",".join(assessment.flags), retry=retry)
            return False
        repository.publish_profile(
            result,
            query_name=(cached or {}).get("query_name", ""),
            quality_flags=assessment.flags,
        )
        repository.complete_refresh_job(job_id)
        return True
    except MissingJobCredential as exc:
        repository.fail_refresh_job(job_id, str(exc), retry=False)
        return False
    except Exception as exc:
        retry = int(job.get("attempts", 1)) < 3
        repository.fail_refresh_job(job_id, str(exc), retry=retry)
        return False


def process_one_graph_job(repository, sync_fn=sync_scholar_research_graph) -> bool:
    """Process one scholar-scoped graph batch without touching prior graph content on failure."""
    job = claim_research_graph_refresh(repository)
    if not job:
        return False
    job_id = str(job["id"])
    try:
        api_key, budget_provider = _job_openalex_credential(repository, job)
        sync_fn(
            repository,
            job["author_id"],
            api_key=api_key,
            budget_provider=budget_provider,
            force_rebuild=bool(job.get("force_rebuild")),
        )
        complete_research_graph_refresh(repository, job_id)
        advance_discoveries_for_candidate(repository, job["author_id"])
        return True
    except MissingJobCredential as exc:
        fail_research_graph_refresh(
            repository,
            job_id,
            str(exc),
            retry=False,
        )
        return False
    except Exception as exc:
        logger.warning(
            "Research graph job %s failed with %s",
            job_id,
            type(exc).__name__,
        )
        public_error = (
            "OpenAlex 暂时无法完成研究图谱更新；本次未写入，"
            "已有成功数据（如有）保持不变。"
            if isinstance(exc, IncompleteGraphSync)
            else "研究图谱后台更新失败；本次未写入，已有成功数据保持不变。"
        )
        fail_research_graph_refresh(
            repository,
            job_id,
            public_error,
            retry=int(job.get("attempts", 1)) < 3,
        )
        advance_discoveries_for_candidate(repository, job["author_id"])
        return False


def process_one_field_discovery_job(repository) -> bool:
    job = claim_field_discovery(repository)
    if not job:
        return False
    try:
        api_key, budget_provider = _job_openalex_credential(repository, job)
    except MissingJobCredential as exc:
        fail_field_discovery(
            repository,
            str(job["id"]),
            str(exc),
            retry=False,
        )
        return False
    return process_claimed_field_discovery(
        repository,
        job,
        api_key=api_key,
        budget_provider=budget_provider,
    )


def _job_openalex_credential(repository, job: dict) -> tuple[str, str]:
    server_api_key = os.getenv("OPENALEX_API_KEY", "").strip()
    if server_api_key:
        return server_api_key, "openalex:server"
    user_id = str(job.get("requested_by_user_id") or "")
    if not user_id:
        raise MissingJobCredential("Refresh job has no requesting user")
    stored = repository.get_user_api_credential(user_id, "openalex")
    if not stored:
        raise MissingJobCredential("Requesting user has no OpenAlex credential")
    try:
        api_key = decrypt_secret(stored["encrypted_secret"])
    except (CredentialConfigurationError, CredentialDecryptionError) as exc:
        raise MissingJobCredential(
            "Requesting user's OpenAlex credential cannot be decrypted"
        ) from exc
    return api_key, f"openalex:user:{user_id}"


def run_forever() -> None:
    repository = create_repository()
    configure_budget_control(
        lambda provider: repository.get_upstream_retry_after(
            provider,
            OPENALEX_MIN_REMAINING_CREDITS,
        ),
        lambda provider, snapshot: repository.record_upstream_rate_limit(
            provider,
            **snapshot,
        ),
    )
    poll_seconds = float(os.getenv("WORKER_POLL_SECONDS", "3"))
    maintenance_seconds = float(os.getenv("WORKER_MAINTENANCE_SECONDS", "3600"))
    run_once = os.getenv("WORKER_ONCE", "").lower() in {"1", "true", "yes"}
    next_maintenance = 0.0
    while True:
        now = time.monotonic()
        if now >= next_maintenance:
            try:
                result = repository.run_maintenance()
                logger.info("Worker maintenance completed: %s", result)
                graph_result = maintain_research_graph_jobs(repository)
                logger.info("Research graph maintenance completed: %s", graph_result)
                discovery_result = maintain_field_discovery_jobs(repository)
                logger.info("Field discovery maintenance completed: %s", discovery_result)
            except Exception:
                logger.exception("Worker maintenance failed")
            next_maintenance = now + maintenance_seconds

        try:
            search_processed = process_one_search_job(repository)
            graph_processed = process_one_graph_job(repository)
            discovery_processed = process_one_field_discovery_job(repository)
            profile_processed = process_one_job(repository)
            processed = (
                search_processed
                or graph_processed
                or discovery_processed
                or profile_processed
            )
        except Exception:
            logger.exception("Worker queue poll failed")
            processed = False
        if run_once:
            return
        if not processed:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    run_forever()
