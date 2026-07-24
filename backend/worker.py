"""Background worker that refreshes due scholar profiles."""
from __future__ import annotations

import logging
import os
import time

from openalex import configure_budget_control
from quality import assess_profile_quality
from repository import create_repository
from search_service import (
    OPENALEX_MIN_REMAINING_CREDITS,
    build_live_candidate_payload,
    run_claimed_search_job,
)
from state import default_state
from workflow import graph


logger = logging.getLogger(__name__)


def process_one_search_job(
    repository,
    builder=build_live_candidate_payload,
) -> bool:
    job = repository.claim_openalex_search_job()
    if not job:
        return False
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
        state = default_state()
        state["target_author_id"] = author_id
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
    except Exception as exc:
        retry = int(job.get("attempts", 1)) < 3
        repository.fail_refresh_job(job_id, str(exc), retry=retry)
        return False


def run_forever() -> None:
    repository = create_repository()
    configure_budget_control(
        lambda: repository.get_upstream_retry_after(
            "openalex",
            OPENALEX_MIN_REMAINING_CREDITS,
        ),
        lambda snapshot: repository.record_upstream_rate_limit("openalex", **snapshot),
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
            except Exception:
                logger.exception("Worker maintenance failed")
            next_maintenance = now + maintenance_seconds

        try:
            search_processed = process_one_search_job(repository)
            profile_processed = process_one_job(repository)
            processed = search_processed or profile_processed
        except Exception:
            logger.exception("Worker queue poll failed")
            processed = False
        if run_once:
            return
        if not processed:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    run_forever()
