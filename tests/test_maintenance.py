import json
from pathlib import Path

from gazeqa.maintenance import rebuild_run_index


def test_rebuild_run_index_cli_helper(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "RUN-LEGACY"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "id": "RUN-LEGACY",
                "target_url": "https://example.test",
                "status": "Pending",
                "organization": "Acme QA",
                "organization_slug": "acme-qa",
            }
        ),
        encoding="utf-8",
    )

    index = rebuild_run_index(tmp_path, move_legacy=True)

    migrated_dir = tmp_path / "acme-qa" / "RUN-LEGACY"
    assert migrated_dir.exists()
    assert index["RUN-LEGACY"]["organization_slug"] == "acme-qa"
