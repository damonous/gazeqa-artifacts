import json
from pathlib import Path

from gazeqa.artifacts import ArtifactManifestBuilder


def test_artifact_manifest_builder(tmp_path: Path) -> None:
    run_id = "RUN-MANIFEST"
    run_dir = tmp_path / run_id
    (run_dir / "docs").mkdir(parents=True)
    sample = run_dir / "docs/sample.txt"
    sample.write_text("hello", encoding="utf-8")
    builder = ArtifactManifestBuilder(storage_root=tmp_path)
    manifest = builder.build(run_id)
    assert manifest["entries"][0]["path"].endswith("docs/sample.txt")
    index = json.loads((run_dir / "artifacts" / "index.json").read_text())
    assert index["run_id"] == run_id
