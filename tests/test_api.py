import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from gazeqa import api

API_TOKEN = "test-token"


def _request(url: str, method: str = "GET", payload: dict | None = None):
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return urllib.request.urlopen(req, timeout=5)


def test_post_runs_success(tmp_path: Path) -> None:
    api.RunRequestHandler.AUTH_TOKEN = ""
    server = api.serve(port=0, storage_root=tmp_path)
    host, port = server.server_address
    url = f"http://{host}:{port}/runs"
    payload = {"target_url": "https://example.test"}
    with _request(url, method="POST", payload=payload) as resp:
        assert resp.status == 201
        body = json.loads(resp.read())
    assert body["status"] == "Running"
    server.shutdown(); server.server_close()


def test_post_runs_validation_error(tmp_path: Path) -> None:
    api.RunRequestHandler.AUTH_TOKEN = ""
    server = api.serve(port=0, storage_root=tmp_path)
    host, port = server.server_address
    url = f"http://{host}:{port}/runs"
    payload = {"target_url": "bad"}
    try:
        _request(url, method="POST", payload=payload)
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
        body = json.loads(exc.read())
        assert body["error"] == "validation_failed"
    else:  # pragma: no cover
        assert False, "Expected HTTPError"
    finally:
        server.shutdown(); server.server_close()


def test_get_runs_pagination_and_events(tmp_path: Path) -> None:
    api.RunRequestHandler.AUTH_TOKEN = API_TOKEN
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

    server.shutdown(); server.server_close()
