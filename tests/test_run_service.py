import json
import shutil
import tempfile
import unittest
from pathlib import Path

from gazeqa.run_service import RunService, ValidationError


class StubOrchestrator:
    def __init__(self, storage_root: Path):
        self.storage_root = storage_root
        self.calls = []

    def authenticate(self, run_id, credentials):  # noqa: D401 - test stub
        self.calls.append(run_id)
        auth_dir = self.storage_root / run_id / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        storage_path = auth_dir / "storageState.json.enc"
        storage_path.write_text("encrypted", encoding="utf-8")
        evidence_path = auth_dir / "session.log"
        evidence_path.write_text("login ok", encoding="utf-8")
        return {
            "stage": "cua",
            "success": True,
            "storage_state_path": str(storage_path),
            "evidence": [str(storage_path), str(evidence_path)],
            "metadata": {"note": "stub"},
        }


class RunServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.service = RunService(storage_root=self.temp_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_run_success(self) -> None:
        payload = {
            "target_url": "https://example.test",
            "credentials": {"username": "qa@example.com", "secret_ref": "vault://creds/1"},
            "budgets": {"time_budget_minutes": 60, "page_budget": 300},
            "storage_profile": "azure-blob",
            "tags": ["smoke", "demo"],
        }
        run_record = self.service.create_run(payload)

        self.assertEqual(run_record["status"], "Running")
        self.assertTrue(run_record["id"].startswith("RUN-"))
        manifest_path = self.temp_dir / run_record["id"] / "run_manifest.json"
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["target_url"], payload["target_url"])

    def test_invalid_payload_raises(self) -> None:
        payload = {"target_url": "not-a-url", "budgets": {"time_budget_minutes": 0}}
        with self.assertRaises(ValidationError) as ctx:
            self.service.create_run(payload)
        self.assertIn("target_url", ctx.exception.errors)
        self.assertIn("budgets.time_budget_minutes", ctx.exception.errors)

    def test_create_run_invokes_auth_when_configured(self) -> None:
        orchestrator = StubOrchestrator(self.temp_dir)
        service = RunService(storage_root=self.temp_dir, auth_orchestrator=orchestrator)
        payload = {
            "target_url": "https://example.test",
            "credentials": {"username": "qa@example.com", "secret_ref": "super-secret"},
        }
        run_record = service.create_run(payload)

        self.assertIn(run_record["id"], orchestrator.calls)
        auth_dir = self.temp_dir / run_record["id"] / "auth"
        self.assertTrue((auth_dir / "storageState.json.enc").exists())

        summary = json.loads(
            (self.temp_dir / run_record["id"] / "run_summary.json").read_text()
        )
        self.assertTrue(summary["auth"]["success"])
        self.assertEqual(summary["auth"]["stage"], "cua")
        self.assertIn("auth/storageState.json.enc", summary["auth"]["evidence"])

    def test_update_status_updates_history(self) -> None:
        payload = {"target_url": "https://example.test"}
        run = self.service.create_run(payload)
        run_id = run["id"]

        self.service.update_status(run_id, "Exploring")
        history = self.service.get_status_history(run_id)
        self.assertEqual(history[-1]["status"], "Exploring")

        manifest = self.service.get_run(run_id)
        self.assertEqual(manifest["status"], "Exploring")

    def test_listener_notified_on_status_change(self) -> None:
        payload = {"target_url": "https://example.test"}
        run = self.service.create_run(payload)
        run_id = run["id"]

        events: list[dict] = []

        def listener(event: dict) -> None:
            events.append(event)

        self.service.register_listener(run_id, listener)
        self.service.update_status(run_id, "Synthesizing")
        self.service.unregister_listener(run_id, listener)

        self.assertTrue(any(evt.get("status") == "Synthesizing" for evt in events))


if __name__ == "__main__":
    unittest.main()
