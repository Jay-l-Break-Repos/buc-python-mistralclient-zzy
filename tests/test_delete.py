"""
Tests for DELETE /api/workflows/<id>

Covers
------
- Returns 204 (no content) on successful deletion
- Returns 404 for an unknown workflow ID
- 404 response body contains an 'error' key mentioning the ID
- Deleting twice returns 404 on the second attempt (idempotency check)
- Deleted workflow no longer appears in GET /api/workflows list
- Deleted workflow returns 404 on GET /api/workflows/<id>
- Physical file is removed from disk after deletion
- Index entry is removed from index.json after deletion
- Other workflows are unaffected when one is deleted
- 204 response has no body
"""

import io
import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Point the storage layer at a fresh temp directory for every test."""
    monkeypatch.setenv("WORKFLOW_STORAGE_DIR", str(tmp_path / "workflow_storage"))
    import importlib
    import app.storage.workflow_store as ws
    importlib.reload(ws)
    yield


@pytest.fixture()
def client(isolated_storage):
    from app.factory import create_app
    application = create_app({"TESTING": True})
    with application.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

VALID_YAML = (
    b"version: '2.0'\n"
    b"name: my_workflow\n"
    b"tasks:\n"
    b"  task1:\n"
    b"    action: std.noop\n"
)

VALID_JSON = b'{"version": "2.0", "name": "json_workflow", "tasks": {}}'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upload(client, filename: str = "wf.yaml", content: bytes = VALID_YAML) -> dict:
    """Upload a file and return the parsed 201 response body."""
    resp = client.post(
        "/api/workflows/upload",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def _storage_dir(monkeypatch_env_value: str | None = None) -> Path:
    """Return the current storage directory path from the module."""
    import app.storage.workflow_store as ws
    return ws.STORAGE_DIR


# ===========================================================================
# DELETE /api/workflows/<id>
# ===========================================================================

class TestDeleteWorkflow:

    # --- Status codes -------------------------------------------------------

    def test_returns_204_on_success(self, client):
        uploaded = _upload(client)
        resp = client.delete(f"/api/workflows/{uploaded['id']}")
        assert resp.status_code == 204

    def test_returns_404_for_unknown_id(self, client):
        resp = client.delete("/api/workflows/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_404_body_has_error_key(self, client):
        resp = client.delete("/api/workflows/nonexistent-id")
        body = resp.get_json()
        assert "error" in body

    def test_404_error_mentions_id(self, client):
        wf_id = "00000000-0000-0000-0000-000000000000"
        body = client.delete(f"/api/workflows/{wf_id}").get_json()
        assert wf_id in body["error"]

    def test_204_response_has_no_body(self, client):
        uploaded = _upload(client)
        resp = client.delete(f"/api/workflows/{uploaded['id']}")
        assert resp.get_data() == b""

    # --- Idempotency --------------------------------------------------------

    def test_second_delete_returns_404(self, client):
        uploaded = _upload(client)
        client.delete(f"/api/workflows/{uploaded['id']}")
        resp = client.delete(f"/api/workflows/{uploaded['id']}")
        assert resp.status_code == 404

    # --- Effect on list endpoint --------------------------------------------

    def test_deleted_workflow_absent_from_list(self, client):
        uploaded = _upload(client)
        client.delete(f"/api/workflows/{uploaded['id']}")
        ids = [w["id"] for w in client.get("/api/workflows").get_json()]
        assert uploaded["id"] not in ids

    def test_list_is_empty_after_deleting_only_workflow(self, client):
        uploaded = _upload(client)
        client.delete(f"/api/workflows/{uploaded['id']}")
        assert client.get("/api/workflows").get_json() == []

    def test_other_workflows_unaffected_in_list(self, client):
        keep = _upload(client, "keep.yaml", VALID_YAML)
        remove = _upload(client, "remove.yaml", VALID_YAML)
        client.delete(f"/api/workflows/{remove['id']}")
        ids = [w["id"] for w in client.get("/api/workflows").get_json()]
        assert keep["id"] in ids
        assert remove["id"] not in ids

    # --- Effect on retrieve endpoint ----------------------------------------

    def test_deleted_workflow_returns_404_on_get(self, client):
        uploaded = _upload(client)
        client.delete(f"/api/workflows/{uploaded['id']}")
        resp = client.get(f"/api/workflows/{uploaded['id']}")
        assert resp.status_code == 404

    def test_other_workflow_still_retrievable_after_delete(self, client):
        keep = _upload(client, "keep.yaml", VALID_YAML)
        remove = _upload(client, "remove.json", VALID_JSON)
        client.delete(f"/api/workflows/{remove['id']}")
        assert client.get(f"/api/workflows/{keep['id']}").status_code == 200

    # --- Storage / disk effects ---------------------------------------------

    def test_file_removed_from_disk(self, client):
        import app.storage.workflow_store as ws
        uploaded = _upload(client)
        # Find the stored filename from the index before deletion.
        index_before = json.loads(ws.INDEX_FILE.read_text())
        stored_name = index_before[uploaded["id"]]["stored_name"]
        file_path = ws.FILES_DIR / stored_name

        assert file_path.exists(), "file should exist before deletion"
        client.delete(f"/api/workflows/{uploaded['id']}")
        assert not file_path.exists(), "file should be gone after deletion"

    def test_index_entry_removed(self, client):
        import app.storage.workflow_store as ws
        uploaded = _upload(client)
        client.delete(f"/api/workflows/{uploaded['id']}")
        index = json.loads(ws.INDEX_FILE.read_text())
        assert uploaded["id"] not in index

    def test_other_index_entries_intact(self, client):
        import app.storage.workflow_store as ws
        keep = _upload(client, "keep.yaml", VALID_YAML)
        remove = _upload(client, "remove.json", VALID_JSON)
        client.delete(f"/api/workflows/{remove['id']}")
        index = json.loads(ws.INDEX_FILE.read_text())
        assert keep["id"] in index
        assert remove["id"] not in index
