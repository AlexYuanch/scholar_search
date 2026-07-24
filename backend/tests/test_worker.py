from repository import InMemoryRepository
from worker import process_one_job, process_one_search_job
from credentials import encrypt_secret


class FakeGraph:
    def invoke(self, state):
        return {
            **state,
            "target_author_profile": {
                "id": state["target_author_id"],
                "display_name": "Ada",
                "works_count": 1,
                "last_known_institutions": [],
            },
            "deduped_works": [{"id": "W1", "title": "Paper", "authorships": []}],
            "works_complete": True,
            "web_payload": {"name": "Ada", "totalPapers": 1},
            "warnings": [],
            "errors": [],
        }


def _seed(repository):
    repository.publish_profile({
        "target_author_id": "A1",
        "target_author_profile": {"id": "A1", "display_name": "Ada", "works_count": 1},
        "deduped_works": [{"id": "W1", "title": "Old", "authorships": []}],
        "works_complete": True,
        "web_payload": {"name": "Ada", "totalPapers": 1},
        "warnings": [],
        "errors": [],
    })


def test_worker_publishes_valid_result_and_completes_job():
    repository = InMemoryRepository()
    _seed(repository)
    job_id = repository.enqueue_refresh("A1", "favorite")

    assert process_one_job(repository, FakeGraph())

    assert repository.jobs[job_id]["status"] == "succeeded"
    assert repository.get_profile("A1")["profile_version"] == 2


def test_worker_keeps_latest_profile_when_quality_gate_fails():
    repository = InMemoryRepository()
    _seed(repository)
    job_id = repository.enqueue_refresh("A1", "favorite")

    class PartialGraph(FakeGraph):
        def invoke(self, state):
            result = super().invoke(state)
            result["works_complete"] = False
            return result

    assert not process_one_job(repository, PartialGraph())

    assert repository.jobs[job_id]["status"] == "pending"
    assert repository.get_profile("A1")["profile_version"] == 1


def test_worker_refreshes_stale_search_cache_and_completes_job():
    repository = InMemoryRepository()
    job_id = repository.enqueue_openalex_search("ada", "Ada")

    def builder(_repository, query_text):
        assert query_text == "Ada"
        return [{"id": "A1", "name": "Ada"}], True

    assert process_one_search_job(repository, builder)
    assert repository.openalex_search_jobs[job_id]["status"] == "succeeded"
    assert repository.get_openalex_search_cache("ada")["candidates"] == [{
        "id": "A1",
        "name": "Ada",
    }]


def test_worker_uses_requesting_users_encrypted_key_for_search(monkeypatch):
    import worker

    repository = InMemoryRepository()
    repository.save_user_api_credential(
        "user-a",
        "openalex",
        encrypt_secret("owned-openalex-key"),
        "••••-key",
    )
    job_id = repository.enqueue_openalex_search(
        "ada",
        "Ada",
        requested_by_user_id="user-a",
    )

    def build(_repository, query_text, *, api_key, budget_provider):
        assert query_text == "Ada"
        assert api_key == "owned-openalex-key"
        assert budget_provider == "openalex:user:user-a"
        return [{"id": "A1", "name": "Ada"}], True

    monkeypatch.setattr(worker, "build_live_candidate_payload", build)

    assert process_one_search_job(repository) is True
    assert repository.openalex_search_jobs[job_id]["status"] == "succeeded"


def test_worker_uses_server_key_when_requesting_user_has_no_key(monkeypatch):
    import worker

    repository = InMemoryRepository()
    job_id = repository.enqueue_openalex_search(
        "ada",
        "Ada",
        requested_by_user_id="user-a",
    )
    monkeypatch.setenv("OPENALEX_API_KEY", "server-openalex-key")

    def build(_repository, query_text, *, api_key, budget_provider):
        assert query_text == "Ada"
        assert api_key == "server-openalex-key"
        assert budget_provider == "openalex:server"
        return [{"id": "A1", "name": "Ada"}], True

    monkeypatch.setattr(worker, "build_live_candidate_payload", build)

    assert process_one_search_job(repository) is True
    assert repository.openalex_search_jobs[job_id]["status"] == "succeeded"


def test_profile_worker_decrypts_key_from_persisted_job_owner():
    repository = InMemoryRepository()
    _seed(repository)
    repository.save_user_api_credential(
        "user-a",
        "openalex",
        encrypt_secret("owned-openalex-key"),
        "••••-key",
    )
    job_id = repository.enqueue_refresh(
        "A1",
        "manual_tracking",
        requested_by_user_id="user-a",
    )

    class CredentialCheckingGraph(FakeGraph):
        def invoke(self, state):
            assert state["openalex_api_key"] == "owned-openalex-key"
            assert state["openalex_budget_provider"] == "openalex:user:user-a"
            return super().invoke(state)

    assert process_one_job(repository, CredentialCheckingGraph()) is True
    assert repository.jobs[job_id]["status"] == "succeeded"


def test_profile_worker_prefers_server_key_without_user_credential(monkeypatch):
    repository = InMemoryRepository()
    _seed(repository)
    job_id = repository.enqueue_refresh(
        "A1",
        "manual_tracking",
        requested_by_user_id="user-a",
    )
    monkeypatch.setenv("OPENALEX_API_KEY", "server-openalex-key")

    class CredentialCheckingGraph(FakeGraph):
        def invoke(self, state):
            assert state["openalex_api_key"] == "server-openalex-key"
            assert state["openalex_budget_provider"] == "openalex:server"
            return super().invoke(state)

    assert process_one_job(repository, CredentialCheckingGraph()) is True
    assert repository.jobs[job_id]["status"] == "succeeded"
