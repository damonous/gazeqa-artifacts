import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from gazeqa import api

API_TOKEN = "test-token"


def _request(url: str, method: str = "GET", payload: dict | None = None, token: str | None = API_TOKEN):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return urllib.request.urlopen(req, timeout=5)


def test_post_runs_success(tmp_path: Path) -> None:
    api.RunRequestHandler.AUTH_TOKEN = ""
    api.RunRequestHandler.TOKEN_REGISTRY = {}
    server = api.serve(port=0, storage_root=tmp_path)
    host, port = server.server_address
    url = f"http://{host}:{port}/runs"
    payload = {"target_url": "https://example.test"}
    with _request(url, method="POST", payload=payload, token=None) as resp:
        assert resp.status == 201
        body = json.loads(resp.read())
    assert body["status"] == "Running"
    server.workflow_executor.shutdown()
    server.shutdown(); server.server_close()


def test_post_runs_validation_error(tmp_path: Path) -> None:
    api.RunRequestHandler.AUTH_TOKEN = ""
    api.RunRequestHandler.TOKEN_REGISTRY = {}
    server = api.serve(port=0, storage_root=tmp_path)
    host, port = server.server_address
    url = f"http://{host}:{port}/runs"
    payload = {"target_url": "bad"}
    try:
        _request(url, method="POST", payload=payload, token=None)
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
        body = json.loads(exc.read())
        assert body["error"] == "validation_failed"
    else:  # pragma: no cover
        assert False, "Expected HTTPError"
    finally:
        server.workflow_executor.shutdown()
        server.shutdown(); server.server_close()


def test_get_runs_pagination_and_events(tmp_path: Path) -> None:
    api.RunRequestHandler.AUTH_TOKEN = API_TOKEN
    api.RunRequestHandler.TOKEN_REGISTRY = {
        API_TOKEN: {
            "organization": "default",
            "organization_slug": "default",
            "actor_role": "qa_runner",
            "scopes": ["runs:create", "runs:read", "runs:events"],
        }
    }
    server = api.serve(port=0, storage_root=tmp_path)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    for idx in range(3):
        payload = {"target_url": f"https://example.test/{idx}"}
        with _request(f"{base}/runs", method="POST", payload=payload) as resp:
            body = json.loads(resp.read())
            run_id = body["id"]

    list_url = f"{base}/runs?offset=1&limit=2"
    with _request(list_url) as resp:
        listing = json.loads(resp.read())
    assert listing["offset"] == 1
    assert listing["limit"] == 2
    assert len(listing["runs"]) == 2
    assert all(isinstance(item, dict) for item in listing["runs"])
    assert all("id" in item for item in listing["runs"])
    assert all(item.get("organization_slug") == "default" for item in listing["runs"])

    server.run_service.update_status(run_id, "Completed")

    events_list_url = f"{base}/runs/{run_id}/events"
    with _request(events_list_url) as resp:
        assert resp.headers["Content-Type"].startswith("application/json")
        body = json.loads(resp.read().decode("utf-8"))
    assert body["run_id"] == run_id
    assert any(evt["status"] == "Completed" for evt in body.get("events", []))

    stream_url = f"{base}/runs/{run_id}/events/stream"
    stream_req = urllib.request.Request(stream_url, headers={"Authorization": f"Bearer {API_TOKEN}"})
    with urllib.request.urlopen(stream_req) as resp:
        assert resp.headers["Content-Type"].startswith("text/event-stream")
        lines = []
        for _ in range(10):
            line = resp.readline().decode("utf-8")
            if not line:
                break
            lines.append(line.strip())
            if line.strip() == "":
                break
    assert any(item.startswith('data:') for item in lines)

    server.workflow_executor.shutdown()
    server.shutdown(); server.server_close()


def test_signed_artifact_download(tmp_path: Path) -> None:
    os.environ["GAZEQA_SIGNING_KEY"] = "secret-key"
    api.RunRequestHandler.AUTH_TOKEN = ""
    api.RunRequestHandler.TOKEN_REGISTRY = {}
    server = api.serve(port=0, storage_root=tmp_path)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        payload = {"target_url": "https://example.test"}
        with _request(f"{base}/runs", method="POST", payload=payload, token=None) as resp:
            run_id = json.loads(resp.read())["id"]

        run_dir = server.run_service.get_run_directory(run_id)
        artifact_dir = run_dir / "reports"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / "sample.txt"
        artifact_path.write_text("hello world", encoding="utf-8")

        manifest = json.loads(_request(f"{base}/runs/{run_id}/artifacts").read().decode("utf-8"))
        entry = next(item for item in manifest["entries"] if item["path"].endswith("sample.txt"))
        download_url = entry["download_url"]
        parsed = urllib.parse.urlsplit(download_url)
        params = urllib.parse.parse_qs(parsed.query)
        assert params.get("organization_slug") == ["default"]
        with urllib.request.urlopen(f"{base}{download_url}") as resp:
            content = resp.read().decode("utf-8")
        assert content == "hello world"
    finally:
        server.workflow_executor.shutdown()
        server.shutdown(); server.server_close()
        os.environ.pop("GAZEQA_SIGNING_KEY", None)


def test_runs_scoped_by_organization(tmp_path: Path) -> None:
    api.RunRequestHandler.AUTH_TOKEN = ""
    api.RunRequestHandler.TOKEN_REGISTRY = {
        "token-acme": {
            "organization": "Acme QA",
            "organization_slug": "acme-qa",
            "actor_role": "qa_runner",
            "scopes": ["runs:create", "runs:read", "runs:events"],
        },
        "token-core": {
            "organization": "Core",
            "organization_slug": "default",
            "actor_role": "qa_runner",
            "scopes": ["runs:create", "runs:read", "runs:events"],
        },
    }
    server = api.serve(port=0, storage_root=tmp_path)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    payload = {"target_url": "https://example.test/a"}
    with _request(f"{base}/runs", method="POST", payload=payload, token="token-acme") as resp:
        run_a = json.loads(resp.read())["id"]

    payload_b = {"target_url": "https://example.test/b"}
    with _request(f"{base}/runs", method="POST", payload=payload_b, token="token-core") as resp:
        run_b = json.loads(resp.read())["id"]

    run_a_dir = server.run_service.get_run_directory(run_a)
    assert "acme-qa" in run_a_dir.parts

    list_url = f"{base}/runs"
    with _request(list_url, token="token-acme") as resp:
        listing = json.loads(resp.read())
    ids = {item["id"] for item in listing["runs"]}
    assert ids == {run_a}

    try:
        _request(f"{base}/runs/{run_b}", token="token-acme")
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
    else:  # pragma: no cover
        assert False, "expected 403 when accessing other org's run"

    server.workflow_executor.shutdown()
    server.shutdown(); server.server_close()


def test_viewer_role_cannot_create_run(tmp_path: Path) -> None:
    api.RunRequestHandler.AUTH_TOKEN = ""
    api.RunRequestHandler.TOKEN_REGISTRY = {
        "token-viewer": {
            "organization": "ViewerOrg",
            "organization_slug": "viewer-org",
            "actor_role": "qa_viewer",
            "scopes": ["runs:read", "runs:events"],
        }
    }
    server = api.serve(port=0, storage_root=tmp_path)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    payload = {"target_url": "https://example.test"}
    try:
        _request(f"{base}/runs", method="POST", payload=payload, token="token-viewer")
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
    else:  # pragma: no cover
        assert False, "expected 403 for viewer create"

    server.workflow_executor.shutdown()
    server.shutdown(); server.server_close()


def test_audit_log_records_run_creation(tmp_path: Path) -> None:
    api.RunRequestHandler.AUTH_TOKEN = ""
    api.RunRequestHandler.TOKEN_REGISTRY = {}
    server = api.serve(port=0, storage_root=tmp_path)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        payload = {"target_url": "https://example.test"}
        with _request(f"{base}/runs", method="POST", payload=payload, token=None) as resp:
            run_id = json.loads(resp.read())["id"]
        audit_path = tmp_path / "_audit" / "audit.log.jsonl"
        assert audit_path.exists()
        entries = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line]
        assert any(entry["action"] == "run.create" and entry["status"] == "success" for entry in entries)
    finally:
        server.workflow_executor.shutdown()
        server.shutdown(); server.server_close()


def test_cors_headers_enforced(tmp_path: Path) -> None:
    os.environ["GAZEQA_ALLOWED_ORIGINS"] = "https://lovable.test"
    api.RunRequestHandler.AUTH_TOKEN = ""
    api.RunRequestHandler.TOKEN_REGISTRY = {}
    server = api.serve(port=0, storage_root=tmp_path)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        request = urllib.request.Request(
            f"{base}/runs",
            headers={"Origin": "https://lovable.test"},
        )
        with urllib.request.urlopen(request) as resp:
            assert resp.headers.get("Access-Control-Allow-Origin") == "https://lovable.test"

        preflight = urllib.request.Request(
            f"{base}/runs",
            method="OPTIONS",
            headers={
                "Origin": "https://lovable.test",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        with urllib.request.urlopen(preflight) as resp:
            assert resp.status == 204
            assert resp.headers.get("Access-Control-Allow-Origin") == "https://lovable.test"
            assert "GET" in resp.headers.get("Access-Control-Allow-Methods", "")
    finally:
        server.workflow_executor.shutdown()
        server.shutdown(); server.server_close()
        os.environ.pop("GAZEQA_ALLOWED_ORIGINS", None)


def test_alert_webhook_requires_token(tmp_path: Path) -> None:
    os.environ["GAZEQA_ALERT_WEBHOOK_TOKEN"] = "alert-secret"
    api.RunRequestHandler.AUTH_TOKEN = ""
    api.RunRequestHandler.TOKEN_REGISTRY = {}
    server = api.serve(port=0, storage_root=tmp_path)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    payload = {
        "alerts": [
            {
                "status": "firing",
                "annotations": {"summary": "Disk space low"},
                "labels": {"alertname": "DiskSpace"},
            }
        ]
    }
    data = json.dumps(payload).encode("utf-8")
    try:
        unauthorized = urllib.request.Request(
            f"{base}/observability/alerts",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(unauthorized)
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        else:  # pragma: no cover
            assert False, "expected forbidden without token"

        authorized = urllib.request.Request(
            f"{base}/observability/alerts",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer alert-secret",
            },
            method="POST",
        )
        with urllib.request.urlopen(authorized) as resp:
            assert resp.status == 202
        audit_path = tmp_path / "_audit" / "audit.log.jsonl"
        entries = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line]
        assert any(entry["action"] == "alert.received" and entry.get("metadata", {}).get("summary") == "Disk space low" for entry in entries)
    finally:
        server.workflow_executor.shutdown()
        server.shutdown(); server.server_close()
        os.environ.pop("GAZEQA_ALERT_WEBHOOK_TOKEN", None)
