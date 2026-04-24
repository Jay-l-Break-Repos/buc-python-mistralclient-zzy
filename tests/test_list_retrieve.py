"""
Tests for:
  GET /api/workflows          – list all workflows
  GET /api/workflows/<id>     – retrieve a specific workflow

Covers
------
- Empty list when no workflows have been uploaded
- List returns all uploaded workflows with correct fields
- List is sorted oldest-first by uploaded_at
- Retrieve returns 200 with metadata + parsed content for YAML and JSON files
- Retrieve returns 404 for an unknown ID
- Content is returned as a structured JSON object (not a raw string)
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

def _upload(client, filename: str, content: bytes) -> dict:
    """Upload a file and return the parsed 201 response body."""
    resp = client.post(
        "/api/workflows/upload",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


# ===========================================================================
# GET /api/workflows  –  list
# ===========================================================================

class TestListWorkflows:
    def test_empty_list_when_no_uploads(self, client):
        resp = client.get("/api/workflows")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_returns_200(self, client):
        _upload(client, "wf.yaml", VALID_YAML)
        assert client.get("/api/workflows").status_code == 200

    def test_response_is_a_list(self, client):
        _upload(client, "wf.yaml", VALID_YAML)
        body = client.get("/api/workflows").get_json()
        assert isinstance(body, list)

    def test_single_upload_appears_in_list(self, client):
        uploaded = _upload(client, "wf.yaml", VALID_YAML)
        body = client.get("/api/workflows").get_json()
        assert len(body) == 1
        assert body[0]["id"] == uploaded["id"]

    def test_multiple_uploads_all_appear(self, client):
        _upload(client, "wf1.yaml", VALID_YAML)
        _upload(client, "wf2.json", VALID_JSON)
        body = client.get("/api/workflows").get_json()
        assert len(body) == 2

    def test_list_item_has_id(self, client):
        _upload(client, "wf.yaml", VALID_YAML)
        item = client.get("/api/workflows").get_json()[0]
        assert "id" in item

    def test_list_item_has_name(self, client):
        _upload(client, "wf.yaml", VALID_YAML)
        item = client.get("/api/workflows").get_json()[0]
        assert item["name"] == "wf.yaml"

    def test_list_item_has_uploaded_at(self, client):
        _upload(client, "wf.yaml", VALID_YAML)
        item = client.get("/api/workflows").get_json()[0]
        assert "uploaded_at" in item

    def test_list_item_has_size(self, client):
        _upload(client, "wf.yaml", VALID_YAML)
        item = client.get("/api/workflows").get_json()[0]
        assert item["size"] == len(VALID_YAML)

    def test_list_item_does_not_contain_content(self, client):
        """The list endpoint should return metadata only, not file content."""
        _upload(client, "wf.yaml", VALID_YAML)
        item = client.get("/api/workflows").get_json()[0]
        assert "content" not in item

    def test_list_sorted_oldest_first(self, client):
        """Items must be ordered by uploaded_at ascending."""
        u1 = _upload(client, "first.yaml", VALID_YAML)
        u2 = _upload(client, "second.yaml", VALID_YAML)
        body = client.get("/api/workflows").get_json()
        ids = [item["id"] for item in body]
        # first upload should appear before second
        assert ids.index(u1["id"]) < ids.index(u2["id"])


# ===========================================================================
# GET /api/workflows/<id>  –  retrieve
# ===========================================================================

class TestGetWorkflow:
    def test_returns_200_for_existing_id(self, client):
        uploaded = _upload(client, "wf.yaml", VALID_YAML)
        resp = client.get(f"/api/workflows/{uploaded['id']}")
        assert resp.status_code == 200

    def test_returns_404_for_unknown_id(self, client):
        resp = client.get("/api/workflows/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_404_body_has_error_key(self, client):
        resp = client.get("/api/workflows/nonexistent-id")
        body = resp.get_json()
        assert "error" in body

    def test_404_error_mentions_id(self, client):
        wf_id = "00000000-0000-0000-0000-000000000000"
        body = client.get(f"/api/workflows/{wf_id}").get_json()
        assert wf_id in body["error"]

    def test_response_has_id(self, client):
        uploaded = _upload(client, "wf.yaml", VALID_YAML)
        body = client.get(f"/api/workflows/{uploaded['id']}").get_json()
        assert body["id"] == uploaded["id"]

    def test_response_has_name(self, client):
        uploaded = _upload(client, "wf.yaml", VALID_YAML)
        body = client.get(f"/api/workflows/{uploaded['id']}").get_json()
        assert body["name"] == "wf.yaml"

    def test_response_has_size(self, client):
        uploaded = _upload(client, "wf.yaml", VALID_YAML)
        body = client.get(f"/api/workflows/{uploaded['id']}").get_json()
        assert body["size"] == len(VALID_YAML)

    def test_response_has_uploaded_at(self, client):
        uploaded = _upload(client, "wf.yaml", VALID_YAML)
        body = client.get(f"/api/workflows/{uploaded['id']}").get_json()
        assert "uploaded_at" in body

    def test_response_has_content_key(self, client):
        uploaded = _upload(client, "wf.yaml", VALID_YAML)
        body = client.get(f"/api/workflows/{uploaded['id']}").get_json()
        assert "content" in body

    def test_yaml_content_is_dict(self, client):
        """YAML content must be returned as a JSON object, not a raw string."""
        uploaded = _upload(client, "wf.yaml", VALID_YAML)
        body = client.get(f"/api/workflows/{uploaded['id']}").get_json()
        assert isinstance(body["content"], dict)

    def test_yaml_content_values_correct(self, client):
        uploaded = _upload(client, "wf.yaml", VALID_YAML)
        body = client.get(f"/api/workflows/{uploaded['id']}").get_json()
        assert body["content"]["name"] == "my_workflow"

    def test_json_content_is_dict(self, client):
        uploaded = _upload(client, "wf.json", VALID_JSON)
        body = client.get(f"/api/workflows/{uploaded['id']}").get_json()
        assert isinstance(body["content"], dict)

    def test_json_content_values_correct(self, client):
        uploaded = _upload(client, "wf.json", VALID_JSON)
        body = client.get(f"/api/workflows/{uploaded['id']}").get_json()
        assert body["content"]["name"] == "json_workflow"

    def test_yml_extension_content_parsed(self, client):
        uploaded = _upload(client, "wf.yml", VALID_YAML)
        body = client.get(f"/api/workflows/{uploaded['id']}").get_json()
        assert isinstance(body["content"], dict)

    def test_retrieve_does_not_affect_list(self, client):
        """Retrieving a workflow must not alter the list count."""
        _upload(client, "wf.yaml", VALID_YAML)
        uploaded = _upload(client, "wf2.json", VALID_JSON)
        client.get(f"/api/workflows/{uploaded['id']}")
        assert len(client.get("/api/workflows").get_json()) == 2
