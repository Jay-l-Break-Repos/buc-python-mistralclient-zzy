"""
Tests for GET /api/workflows/<id> (retrieve a specific workflow)

Covers
------
- 200 response for a valid workflow ID
- Response contains id, name, size, uploaded_at, and content fields
- content field matches the original uploaded data (YAML → dict, JSON → dict)
- Works for all three accepted extensions (.yaml, .yml, .json)
- 404 with error message for a non-existent ID
- 404 error message references the requested ID
- id, name, size, uploaded_at values match those returned at upload time
- content is a JSON-serialisable object (dict/list), not a raw string
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

VALID_YAML = (
    b"version: '2.0'\n"
    b"name: my_workflow\n"
    b"tasks:\n"
    b"  task1:\n"
    b"    action: std.noop\n"
)

VALID_YML = (
    b"version: '2.0'\n"
    b"name: yml_workflow\n"
)

VALID_JSON = b'{"version": "2.0", "name": "json_workflow", "tasks": {}}'


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


def _get(client, workflow_id: str):
    """Call GET /api/workflows/<id> and return (status_code, body)."""
    resp = client.get(f"/api/workflows/{workflow_id}")
    return resp.status_code, resp.get_json()


# ===========================================================================
# GET /api/workflows/<id>
# ===========================================================================

class TestRetrieveWorkflow:

    # --- Happy path: status and shape ---------------------------------------

    def test_returns_200_for_valid_id(self, client):
        upload = _upload(client)
        status, _ = _get(client, upload["id"])
        assert status == 200

    def test_response_has_id(self, client):
        upload = _upload(client)
        _, body = _get(client, upload["id"])
        assert "id" in body

    def test_response_has_name(self, client):
        upload = _upload(client)
        _, body = _get(client, upload["id"])
        assert "name" in body

    def test_response_has_size(self, client):
        upload = _upload(client)
        _, body = _get(client, upload["id"])
        assert "size" in body

    def test_response_has_uploaded_at(self, client):
        upload = _upload(client)
        _, body = _get(client, upload["id"])
        assert "uploaded_at" in body

    def test_response_has_content(self, client):
        upload = _upload(client)
        _, body = _get(client, upload["id"])
        assert "content" in body

    # --- Field values match upload response ---------------------------------

    def test_id_matches_upload(self, client):
        upload = _upload(client)
        _, body = _get(client, upload["id"])
        assert body["id"] == upload["id"]

    def test_name_matches_upload(self, client):
        upload = _upload(client, "my_flow.yaml")
        _, body = _get(client, upload["id"])
        assert body["name"] == "my_flow.yaml"

    def test_size_matches_upload(self, client):
        upload = _upload(client)
        _, body = _get(client, upload["id"])
        assert body["size"] == upload["size"]

    def test_uploaded_at_matches_upload(self, client):
        upload = _upload(client)
        _, body = _get(client, upload["id"])
        assert body["uploaded_at"] == upload["uploaded_at"]

    # --- Content field correctness ------------------------------------------

    def test_content_is_dict_for_yaml(self, client):
        upload = _upload(client, "wf.yaml", VALID_YAML)
        _, body = _get(client, upload["id"])
        assert isinstance(body["content"], dict)

    def test_content_is_dict_for_yml(self, client):
        upload = _upload(client, "wf.yml", VALID_YML)
        _, body = _get(client, upload["id"])
        assert isinstance(body["content"], dict)

    def test_content_is_dict_for_json(self, client):
        upload = _upload(client, "wf.json", VALID_JSON)
        _, body = _get(client, upload["id"])
        assert isinstance(body["content"], dict)

    def test_yaml_content_has_correct_values(self, client):
        upload = _upload(client, "wf.yaml", VALID_YAML)
        _, body = _get(client, upload["id"])
        assert body["content"]["name"] == "my_workflow"
        assert body["content"]["version"] == "2.0"

    def test_json_content_has_correct_values(self, client):
        upload = _upload(client, "wf.json", VALID_JSON)
        _, body = _get(client, upload["id"])
        assert body["content"]["name"] == "json_workflow"
        assert body["content"]["version"] == "2.0"

    def test_content_is_not_a_string(self, client):
        """content must be a parsed object, not a raw YAML/JSON string."""
        upload = _upload(client)
        _, body = _get(client, upload["id"])
        assert not isinstance(body["content"], str)

    # --- 404 for unknown ID -------------------------------------------------

    def test_returns_404_for_unknown_id(self, client):
        status, _ = _get(client, "00000000-0000-0000-0000-000000000000")
        assert status == 404

    def test_404_response_has_error_key(self, client):
        _, body = _get(client, "00000000-0000-0000-0000-000000000000")
        assert "error" in body

    def test_404_error_message_contains_id(self, client):
        missing_id = "00000000-0000-0000-0000-000000000000"
        _, body = _get(client, missing_id)
        assert missing_id in body["error"]

    def test_404_after_uploading_different_workflow(self, client):
        """Uploading one workflow must not make a different ID retrievable."""
        _upload(client)
        status, _ = _get(client, "ffffffff-ffff-ffff-ffff-ffffffffffff")
        assert status == 404
