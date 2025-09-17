import json
from pathlib import Path

from gazeqa.bfs import BFSCrawler, CrawlConfig
from gazeqa.exploration import ExplorationConfig, ExplorationEngine, PageDescriptor
from gazeqa.run_service import RunService
from gazeqa.observability import RunObservability
from gazeqa.workflow import RetryPolicy, RetryableWorkflowError, RunWorkflow, WorkflowError


class SuccessfulAuth:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def authenticate(self, run_id, _credentials):  # noqa: D401 - stub for tests
        self.calls.append(run_id)
        return {
            "success": True,
            "stage": "cua",
            "storage_state_path": "encrypted",
        }


class FlakyAuth(SuccessfulAuth):
    def __init__(self, fail_attempts: int = 1) -> None:
        super().__init__()
        self.fail_attempts = fail_attempts

    def authenticate(self, run_id, credentials):  # noqa: D401 - stub for tests
        if len(self.calls) < self.fail_attempts:
            self.calls.append(run_id)
            raise RetryableWorkflowError("transient auth failure")
        return super().authenticate(run_id, credentials)


def _page(page_id: str, suffix: str, title: str) -> PageDescriptor:
    return PageDescriptor(
        url=f"https://example.test/{suffix}",
        title=title,
        section="mission",
        page_id=page_id,
    )


def _checkpoint_entries(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_workflow_success_records_checkpoints(tmp_path: Path) -> None:
    auth = SuccessfulAuth()
    run_service = RunService(storage_root=tmp_path)
    exploration_engine = ExplorationEngine(ExplorationConfig(storage_root=tmp_path))
    crawler = BFSCrawler(CrawlConfig(storage_root=tmp_path))
    telemetry = RunObservability(storage_root=tmp_path)
    workflow = RunWorkflow(run_service, auth, exploration_engine, crawler, telemetry=telemetry)

    home = _page("home", "home", "Home")
    about = _page("about", "about", "About")
    team = _page("team", "team", "Team")
    admin = _page("admin", "admin", "Admin")
    site_map = [home, about, team, admin]
    adjacency = {
        "home": [about, team],
        "about": [admin],
    }

    payload = {
        "target_url": "https://example.test",
        "credentials": {"username": "qa@example.com", "secret_ref": "vault://creds/1"},
    }

    result = workflow.start(payload_dict=payload, site_map=site_map, adjacency=adjacency)
    run_id = result["run_id"]

    status_history = run_service.get_status_history(run_id)
    assert status_history[-1]["status"] == "Completed"

    checkpoint_path = tmp_path / run_id / "temporal" / "checkpoints.jsonl"
    entries = _checkpoint_entries(checkpoint_path)
    checkpoints = {entry["checkpoint"] for entry in entries}
    assert "auth.attempt" in checkpoints
    assert "workflow.completed" in checkpoints

    assert auth.calls == [run_id]
    assert result["crawl"]["visited_count"] >= 2

    metrics_path = tmp_path / run_id / "observability" / "metrics.json"
    metrics = json.loads(metrics_path.read_text())
    assert metrics["exploration"]["coverage_percent"] is not None
    assert metrics["crawl"]["visited_count"] >= 1


def test_workflow_retries_auth_until_success(tmp_path: Path) -> None:
    auth = FlakyAuth()
    run_service = RunService(storage_root=tmp_path)
    exploration_engine = ExplorationEngine(ExplorationConfig(storage_root=tmp_path))
    crawler = BFSCrawler(CrawlConfig(storage_root=tmp_path))
    workflow = RunWorkflow(
        run_service,
        auth,
        exploration_engine,
        crawler,
        retry_policy=RetryPolicy(max_attempts=3, backoff_seconds=(0.0, 0.0, 0.0)),
    )

    home = _page("home", "home", "Home")
    about = _page("about", "about", "About")
    site_map = [home, about]
    adjacency = {"home": [about]}

    payload = {
        "target_url": "https://example.test",
        "credentials": {"username": "qa@example.com", "secret_ref": "vault://creds/1"},
    }

    run_record = run_service.create_run(payload)
    workflow.execute(run_record["id"], site_map=site_map, adjacency=adjacency)

    checkpoint_path = tmp_path / run_record["id"] / "temporal" / "checkpoints.jsonl"
    entries = _checkpoint_entries(checkpoint_path)
    auth_retries = [entry for entry in entries if entry["checkpoint"] == "auth.retry"]
    assert auth_retries, "expected retry checkpoint"

    history = run_service.get_status_history(run_record["id"])
    assert history[-1]["status"] == "Completed"


def test_workflow_failure_sets_failed_status(tmp_path: Path) -> None:
    auth = SuccessfulAuth()
    run_service = RunService(storage_root=tmp_path)
    exploration_engine = ExplorationEngine(ExplorationConfig(storage_root=tmp_path))
    crawler = BFSCrawler(CrawlConfig(storage_root=tmp_path))
    workflow = RunWorkflow(run_service, auth, exploration_engine, crawler)

    home = _page("home", "home", "Home")
    site_map = [home]
    adjacency: dict[str, list[PageDescriptor]] = {}

    payload = {
        "target_url": "https://example.test",
        "credentials": {"username": "qa@example.com", "secret_ref": "vault://creds/1"},
    }

    run_record = run_service.create_run(payload)

    def make_failure(*_args, **_kwargs):
        raise WorkflowError("exploration failure")

    workflow.exploration_engine.explore = make_failure  # type: ignore[assignment]

    try:
        workflow.execute(run_record["id"], site_map=site_map, adjacency=adjacency)
    except WorkflowError:
        pass
    else:  # pragma: no cover - ensure failure propagates
        assert False, "expected WorkflowError"

    history = run_service.get_status_history(run_record["id"])
    assert history[-1]["status"] == "Failed"

    checkpoint_path = tmp_path / run_record["id"] / "temporal" / "checkpoints.jsonl"
    entries = _checkpoint_entries(checkpoint_path)
    assert any(entry["checkpoint"] == "workflow.failed" for entry in entries)


def test_workflow_skips_auth_when_orchestrator_missing(tmp_path: Path) -> None:
    run_service = RunService(storage_root=tmp_path)
    exploration_engine = ExplorationEngine(ExplorationConfig(storage_root=tmp_path))
    crawler = BFSCrawler(CrawlConfig(storage_root=tmp_path))
    workflow = RunWorkflow(run_service, None, exploration_engine, crawler)

    home = _page("home", "home", "Home")
    about = _page("about", "about", "About")
    site_map = [home, about]
    adjacency = {"home": [about]}

    payload = {
        "target_url": "https://example.test",
        "credentials": {"username": "qa@example.com", "secret_ref": "vault://creds/1"},
    }

    result = workflow.start(payload_dict=payload, site_map=site_map, adjacency=adjacency)
    auth_result = result["auth"]
    assert auth_result["stage"] == "skipped"
    assert auth_result["reason"] == "orchestrator_unavailable"
