import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from gazeqa import api


def _post(url: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    return urllib.request.urlopen(req, timeout=5)


def test_post_runs_success(tmp_path: Path) -> None:
    server = api.serve(port=0, storage_root=tmp_path)
    host, port = server.server_address
    url = f"http://{host}:{port}/runs"
    payload = {"target_url": "https://example.test"}
    with _post(url, payload) as resp:
        assert resp.status == 201
        body = json.loads(resp.read())
    assert body["status"] == "Pending"
    server.shutdown(); server.server_close()


def test_post_runs_validation_error(tmp_path: Path) -> None:
    server = api.serve(port=0, storage_root=tmp_path)
    host, port = server.server_address
    url = f"http://{host}:{port}/runs"
    payload = {"target_url": "bad"}
    try:
        _post(url, payload)
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
        body = json.loads(exc.read())
        assert body["error"] == "validation_failed"
    else:  # pragma: no cover
        assert False, "Expected HTTPError"
    finally:
        server.shutdown(); server.server_close()


def test_get_runs_pagination_and_events(tmp_path: Path) -> None:
    server = api.serve(port=0, storage_root=tmp_path)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    # create two runs
    for idx in range(3):
        payload = {"target_url": f"https://example.test/{idx}"}
        with _post(f"{base}/runs", payload) as resp:
            body = json.loads(resp.read())
            run_id = body["id"]

    list_url = f"{base}/runs?offset=1&limit=2"
    with urllib.request.urlopen(list_url) as resp:
        listing = json.loads(resp.read())
    assert listing["offset"] == 1
    assert listing["limit"] == 2
    assert len(listing["runs"]) == 2

    events_url = f"{base}/runs/{run_id}/events"
    with urllib.request.urlopen(events_url) as resp:
        events = json.loads(resp.read())
    assert events["run_id"] == run_id
    assert events["events"][0]["event"] == "run.created"

    server.shutdown(); server.server_close()
