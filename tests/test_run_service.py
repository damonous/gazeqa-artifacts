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

    def authenticate(
        self,
        run_id,
        credentials,
        *,
        run_dir=None,
        organization_slug=None,
    ):  # noqa: D401 - test stub
        self.calls.append(run_id)
        base_dir = run_dir or (self.storage_root / (organization_slug or "default") / run_id)
        auth_dir = base_dir / "auth"
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
        run_dir = self.service.get_run_directory(run_record["id"])
        manifest_path = run_dir / "run_manifest.json"
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["target_url"], payload["target_url"])
        self.assertEqual(manifest["organization_slug"], "default")

    def test_create_run_with_custom_organization(self) -> None:
        payload = {
            "target_url": "https://example.test/custom",
            "organization": "Acme QA",
            "organization_slug": "acme-qa",
            "actor_role": "qa_runner",
        }
        run_record = self.service.create_run(payload)
        self.assertEqual(run_record["organization_slug"], "acme-qa")
        run_dir = self.service.get_run_directory(run_record["id"])
        self.assertIn("acme-qa", run_dir.parts)
        manifest = self.service.get_run(run_record["id"])
        self.assertEqual(manifest["organization_slug"], "acme-qa")

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
        run_dir = service.get_run_directory(run_record["id"])
        auth_dir = run_dir / "auth"
        self.assertTrue((auth_dir / "storageState.json.enc").exists())

        summary = json.loads((run_dir / "run_summary.json").read_text())
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

    def test_rebuild_index_moves_legacy_runs(self) -> None:
        legacy_dir = self.temp_dir / "RUN-LEGACY"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "id": "RUN-LEGACY",
                    "target_url": "https://example.test/legacy",
                    "status": "Completed",
                    "organization": "Legacy",
                    "organization_slug": "legacy",
                }
            ),
            encoding="utf-8",
        )
        self.service.rebuild_index(move_legacy=True)

        migrated_dir = self.temp_dir / "legacy" / "RUN-LEGACY"
        self.assertTrue(migrated_dir.exists())

        index_path = self.temp_dir / "run_index.json"
        index = json.loads(index_path.read_text())
        self.assertEqual(index["RUN-LEGACY"]["organization_slug"], "legacy")


if __name__ == "__main__":
    unittest.main()
