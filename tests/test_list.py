"""
Tests for GET /api/workflows (list all uploaded workflows)

Covers
------
- Empty list when no workflows have been uploaded
- Returns 200 with a JSON array
- Each item contains id, name, and uploaded_at (minimum required fields)
- Each item also contains size
- List grows as workflows are uploaded
- All uploaded workflows appear in the list
- IDs in the list match the IDs returned at upload time
- Response is a JSON array (not an object)
- Ordering: oldest upload first (ascending uploaded_at)
"""

import io

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
VALID_JSON = b'{"version": "2.0", "name": "my_workflow"}'


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


def _list(client):
    """Call GET /api/workflows and return (status_code, body)."""
    resp = client.get("/api/workflows")
    return resp.status_code, resp.get_json()


# ===========================================================================
# GET /api/workflows
# ===========================================================================

class TestListWorkflows:

    # --- Basic response shape -----------------------------------------------

    def test_returns_200(self, client):
        status, _ = _list(client)
        assert status == 200

    def test_returns_json_array(self, client):
        _, body = _list(client)
        assert isinstance(body, list)

    def test_empty_list_when_no_uploads(self, client):
        _, body = _list(client)
        assert body == []

    # --- Required fields in each item ---------------------------------------

    def test_item_has_id(self, client):
        _upload(client)
        _, body = _list(client)
        assert "id" in body[0]

    def test_item_has_name(self, client):
        _upload(client, "workflow.yaml")
        _, body = _list(client)
        assert "name" in body[0]

    def test_item_has_uploaded_at(self, client):
        _upload(client)
        _, body = _list(client)
        assert "uploaded_at" in body[0]

    def test_item_has_size(self, client):
        _upload(client)
        _, body = _list(client)
        assert "size" in body[0]

    # --- Field values -------------------------------------------------------

    def test_name_matches_uploaded_filename(self, client):
        _upload(client, "my_workflow.yaml")
        _, body = _list(client)
        assert body[0]["name"] == "my_workflow.yaml"

    def test_id_matches_upload_response(self, client):
        upload_body = _upload(client)
        _, body = _list(client)
        assert body[0]["id"] == upload_body["id"]

    def test_size_matches_upload_response(self, client):
        upload_body = _upload(client)
        _, body = _list(client)
        assert body[0]["size"] == upload_body["size"]

    # --- Multiple uploads ---------------------------------------------------

    def test_list_grows_with_each_upload(self, client):
        assert _list(client)[1] == []
        _upload(client, "wf1.yaml")
        assert len(_list(client)[1]) == 1
        _upload(client, "wf2.yaml")
        assert len(_list(client)[1]) == 2

    def test_all_uploaded_workflows_appear_in_list(self, client):
        id1 = _upload(client, "wf1.yaml")["id"]
        id2 = _upload(client, "wf2.json", VALID_JSON)["id"]
        id3 = _upload(client, "wf3.yml")["id"]
        _, body = _list(client)
        ids_in_list = {item["id"] for item in body}
        assert {id1, id2, id3} == ids_in_list

    def test_list_contains_correct_names(self, client):
        _upload(client, "alpha.yaml")
        _upload(client, "beta.json", VALID_JSON)
        _, body = _list(client)
        names = {item["name"] for item in body}
        assert names == {"alpha.yaml", "beta.json"}

    # --- Ordering -----------------------------------------------------------

    def test_list_ordered_oldest_first(self, client):
        """Uploads should appear in ascending uploaded_at order."""
        id1 = _upload(client, "first.yaml")["id"]
        id2 = _upload(client, "second.yaml")["id"]
        _, body = _list(client)
        assert body[0]["id"] == id1
        assert body[1]["id"] == id2

    # --- Response is an array, not an object --------------------------------

    def test_response_is_not_wrapped_in_object(self, client):
        """The top-level response must be a JSON array, not {'workflows': [...]}."""
        _upload(client)
        _, body = _list(client)
        assert isinstance(body, list), "Expected a top-level JSON array"
        assert "workflows" not in body  # body is a list, so this is always true
