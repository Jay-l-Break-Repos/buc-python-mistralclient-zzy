"""
Tests for DELETE /api/workflows/<id> (delete a specific workflow)

Covers
------
- 204 No Content on successful deletion
- No response body on 204
- Physical file is removed from disk after deletion
- Index entry is removed from index.json after deletion
- Deleted workflow no longer appears in GET /api/workflows list
- GET /api/workflows/<id> returns 404 after deletion
- Second DELETE on the same ID returns 404
- 404 with error message for a non-existent ID
- 404 error message references the requested ID
- Deleting one workflow does not affect other workflows
- Other workflows remain retrievable after an unrelated deletion
- List count decreases by exactly one after deletion
"""

import io
import json

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

VALID_YAML = b"version: '2.0'\nname: my_workflow\ntasks:\n  task1:\n    action: std.noop\n"
VALID_JSON = b'{"version": "2.0", "name": "json_workflow"}'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upload(client, filename: str = "wf.yaml", content: bytes = VALID_YAML) -> dict:
    """Upload a workflow and return the parsed 201 response body."""
    resp = client.post(
        "/api/workflows/upload",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def _delete(client, workflow_id: str):
    """Call DELETE /api/workflows/<id> and return (status_code, response)."""
    resp = client.delete(f"/api/workflows/{workflow_id}")
    return resp.status_code, resp


def _get(client, workflow_id: str):
    resp = client.get(f"/api/workflows/{workflow_id}")
    return resp.status_code, resp.get_json()


def _list(client):
    resp = client.get("/api/workflows")
    return resp.status_code, resp.get_json()


def _storage_files_dir(monkeypatch_env_value: str | None = None):
    """Return the FILES_DIR path used by the reloaded storage module."""
    import app.storage.workflow_store as ws
    return ws.FILES_DIR


# ===========================================================================
# DELETE /api/workflows/<id>
# ===========================================================================

class TestDeleteWorkflow:

    # --- Happy path: status and body ----------------------------------------

    def test_returns_204_on_success(self, client):
        upload = _upload(client)
        status, _ = _delete(client, upload["id"])
        assert status == 204

    def test_204_response_has_no_body(self, client):
        upload = _upload(client)
        _, resp = _delete(client, upload["id"])
        assert resp.get_data() == b""

    # --- Physical file removal ----------------------------------------------

    def test_file_removed_from_disk(self, client):
        import app.storage.workflow_store as ws
        upload = _upload(client)
        # Confirm the file exists before deletion.
        files = list(ws.FILES_DIR.iterdir())
        assert len(files) == 1
        # Delete.
        _delete(client, upload["id"])
        # File must be gone.
        assert list(ws.FILES_DIR.iterdir()) == []

    # --- Index entry removal ------------------------------------------------

    def test_index_entry_removed(self, client):
        import app.storage.workflow_store as ws
        upload = _upload(client)
        _delete(client, upload["id"])
        index = json.loads(ws.INDEX_FILE.read_text())
        assert upload["id"] not in index

    def test_index_file_still_exists_after_deletion(self, client):
        import app.storage.workflow_store as ws
        upload = _upload(client)
        _delete(client, upload["id"])
        assert ws.INDEX_FILE.exists()

    # --- Subsequent requests reflect deletion --------------------------------

    def test_deleted_workflow_absent_from_list(self, client):
        upload = _upload(client)
        _delete(client, upload["id"])
        _, body = _list(client)
        ids = [item["id"] for item in body]
        assert upload["id"] not in ids

    def test_get_returns_404_after_deletion(self, client):
        upload = _upload(client)
        _delete(client, upload["id"])
        status, _ = _get(client, upload["id"])
        assert status == 404

    def test_second_delete_returns_404(self, client):
        upload = _upload(client)
        _delete(client, upload["id"])
        status, _ = _delete(client, upload["id"])
        assert status == 404

    # --- 404 for unknown ID -------------------------------------------------

    def test_returns_404_for_unknown_id(self, client):
        status, _ = _delete(client, "00000000-0000-0000-0000-000000000000")
        assert status == 404

    def test_404_response_has_error_key(self, client):
        _, resp = _delete(client, "00000000-0000-0000-0000-000000000000")
        body = resp.get_json()
        assert "error" in body

    def test_404_error_message_contains_id(self, client):
        missing_id = "00000000-0000-0000-0000-000000000000"
        _, resp = _delete(client, missing_id)
        body = resp.get_json()
        assert missing_id in body["error"]

    # --- Isolation: other workflows unaffected ------------------------------

    def test_other_workflows_remain_in_list(self, client):
        id1 = _upload(client, "wf1.yaml")["id"]
        id2 = _upload(client, "wf2.yaml")["id"]
        _delete(client, id1)
        _, body = _list(client)
        ids = [item["id"] for item in body]
        assert id2 in ids
        assert id1 not in ids

    def test_other_workflow_still_retrievable(self, client):
        id1 = _upload(client, "wf1.yaml")["id"]
        id2 = _upload(client, "wf2.json", VALID_JSON)["id"]
        _delete(client, id1)
        status, _ = _get(client, id2)
        assert status == 200

    def test_list_count_decreases_by_one(self, client):
        _upload(client, "wf1.yaml")
        id2 = _upload(client, "wf2.yaml")["id"]
        _upload(client, "wf3.yaml")
        _, before = _list(client)
        _delete(client, id2)
        _, after = _list(client)
        assert len(after) == len(before) - 1

    def test_other_workflow_file_still_on_disk(self, client):
        import app.storage.workflow_store as ws
        _upload(client, "wf1.yaml")
        id2 = _upload(client, "wf2.yaml")["id"]
        _delete(client, id2)
        # wf1's file must still be present.
        assert len(list(ws.FILES_DIR.iterdir())) == 1
