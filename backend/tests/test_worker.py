from repository import InMemoryRepository
from worker import process_one_job


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
