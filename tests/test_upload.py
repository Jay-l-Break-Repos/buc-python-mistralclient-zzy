"""
Tests for the Workflow API

Endpoints covered
-----------------
POST   /api/workflows/upload   – upload a YAML or JSON workflow file
GET    /api/workflows           – list all uploaded workflows
GET    /api/workflows/<id>      – retrieve a specific workflow's raw content
DELETE /api/workflows/<id>      – delete a workflow
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
VALID_JSON = b'{"version": "2.0", "name": "my_workflow"}'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upload(client, filename: str, content: bytes, field: str = "file"):
    """Send a multipart upload request and return the response."""
    data = {field: (io.BytesIO(content), filename)}
    return client.post(
        "/api/workflows/upload",
        data=data,
        content_type="multipart/form-data",
    )


def _upload_ok(client, filename: str = "wf.yaml", content: bytes = VALID_YAML) -> dict:
    """Upload a valid file and return the parsed JSON body (asserts 201)."""
    resp = _upload(client, filename, content)
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


# ===========================================================================
# GET / — health check
# ===========================================================================

class TestHealthCheck:
    def test_root_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_root_returns_json_status_ok(self, client):
        body = client.get("/").get_json()
        assert body == {"status": "ok"}


# ===========================================================================
# POST /api/workflows/upload
# ===========================================================================

class TestUploadHappyPath:
    def test_returns_201(self, client):
        resp = _upload(client, "workflow.yaml", VALID_YAML)
        assert resp.status_code == 201

    def test_response_has_id(self, client):
        body = _upload_ok(client)
        assert "id" in body

    def test_response_has_name(self, client):
        body = _upload_ok(client, "workflow.yaml")
        assert body["name"] == "workflow.yaml"

    def test_response_has_size(self, client):
        body = _upload_ok(client, "wf.yaml", VALID_YAML)
        assert body["size"] == len(VALID_YAML)

    def test_response_has_uploaded_at(self, client):
        body = _upload_ok(client)
        assert "uploaded_at" in body

    def test_yaml_extension_accepted(self, client):
        assert _upload(client, "wf.yaml", VALID_YAML).status_code == 201

    def test_yml_extension_accepted(self, client):
        assert _upload(client, "wf.yml", VALID_YAML).status_code == 201

    def test_json_extension_accepted(self, client):
        assert _upload(client, "wf.json", VALID_JSON).status_code == 201

    def test_each_upload_gets_unique_id(self, client):
        id1 = _upload_ok(client)["id"]
        id2 = _upload_ok(client)["id"]
        assert id1 != id2

    def test_response_is_flat_not_nested(self, client):
        """id and name must be top-level keys, not nested under 'workflow'."""
        body = _upload_ok(client)
        assert "workflow" not in body
        assert "id" in body
        assert "name" in body


class TestUploadValidationErrors:
    def test_missing_file_field_returns_400(self, client):
        resp = client.post("/api/workflows/upload", data={},
                           content_type="multipart/form-data")
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_empty_filename_returns_400(self, client):
        data = {"file": (io.BytesIO(VALID_YAML), "")}
        resp = client.post("/api/workflows/upload", data=data,
                           content_type="multipart/form-data")
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_txt_extension_returns_400(self, client):
        resp = _upload(client, "workflow.txt", VALID_YAML)
        assert resp.status_code == 400
        body = resp.get_json()
        assert "error" in body
        assert ".txt" in body["error"]

    def test_xml_extension_returns_400(self, client):
        resp = _upload(client, "workflow.xml", b"<root/>")
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_no_extension_returns_400(self, client):
        resp = _upload(client, "workflow", VALID_YAML)
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_error_mentions_allowed_types(self, client):
        body = _upload(client, "workflow.csv", b"a,b,c").get_json()
        msg = body["error"].lower()
        assert "yaml" in msg or "yml" in msg or "json" in msg

    def test_malformed_yaml_returns_400(self, client):
        resp = _upload(client, "bad.yaml", b"key: [unclosed bracket\n  - item\n")
        assert resp.status_code == 400
        body = resp.get_json()
        assert "error" in body
        assert "yaml" in body["error"].lower()

    def test_malformed_json_returns_400(self, client):
        resp = _upload(client, "bad.json", b'{"key": "value", "broken":')
        assert resp.status_code == 400
        body = resp.get_json()
        assert "error" in body
        assert "json" in body["error"].lower()


# ===========================================================================
# GET /api/workflows
# ===========================================================================

class TestListWorkflows:
    def test_empty_list_on_fresh_storage(self, client):
        resp = client.get("/api/workflows")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body == []

    def test_returns_uploaded_workflow(self, client):
        _upload_ok(client, "wf.yaml")
        resp = client.get("/api/workflows")
        assert resp.status_code == 200
        workflows = resp.get_json()
        assert len(workflows) == 1

    def test_list_entry_has_id_and_name(self, client):
        _upload_ok(client, "my.yaml")
        entry = client.get("/api/workflows").get_json()[0]
        assert "id" in entry
        assert entry["name"] == "my.yaml"

    def test_list_entry_has_size_and_uploaded_at(self, client):
        _upload_ok(client, "wf.yaml", VALID_YAML)
        entry = client.get("/api/workflows").get_json()[0]
        assert entry["size"] == len(VALID_YAML)
        assert "uploaded_at" in entry

    def test_multiple_uploads_all_listed(self, client):
        _upload_ok(client, "a.yaml")
        _upload_ok(client, "b.json", VALID_JSON)
        _upload_ok(client, "c.yml")
        workflows = client.get("/api/workflows").get_json()
        assert len(workflows) == 3

    def test_list_ids_match_upload_ids(self, client):
        id1 = _upload_ok(client, "a.yaml")["id"]
        id2 = _upload_ok(client, "b.yaml")["id"]
        listed_ids = {w["id"] for w in client.get("/api/workflows").get_json()}
        assert {id1, id2} == listed_ids


# ===========================================================================
# GET /api/workflows/<id>
# ===========================================================================

class TestRetrieveWorkflow:
    def test_returns_200_for_existing_workflow(self, client):
        wf_id = _upload_ok(client, "wf.yaml")["id"]
        resp = client.get(f"/api/workflows/{wf_id}")
        assert resp.status_code == 200

    def test_response_is_json(self, client):
        wf_id = _upload_ok(client, "wf.yaml", VALID_YAML)["id"]
        resp = client.get(f"/api/workflows/{wf_id}")
        assert resp.is_json

    def test_response_has_content_field(self, client):
        wf_id = _upload_ok(client, "wf.yaml", VALID_YAML)["id"]
        body = client.get(f"/api/workflows/{wf_id}").get_json()
        assert "content" in body

    def test_content_matches_uploaded_yaml(self, client):
        wf_id = _upload_ok(client, "wf.yaml", VALID_YAML)["id"]
        body = client.get(f"/api/workflows/{wf_id}").get_json()
        assert body["content"] == VALID_YAML.decode("utf-8")

    def test_content_matches_uploaded_json(self, client):
        wf_id = _upload_ok(client, "wf.json", VALID_JSON)["id"]
        body = client.get(f"/api/workflows/{wf_id}").get_json()
        assert body["content"] == VALID_JSON.decode("utf-8")

    def test_response_includes_metadata_fields(self, client):
        wf_id = _upload_ok(client, "wf.yaml", VALID_YAML)["id"]
        body = client.get(f"/api/workflows/{wf_id}").get_json()
        assert body["id"] == wf_id
        assert body["name"] == "wf.yaml"
        assert body["size"] == len(VALID_YAML)
        assert "uploaded_at" in body

    def test_returns_404_for_unknown_id(self, client):
        resp = client.get("/api/workflows/nonexistent-id")
        assert resp.status_code == 404
        assert "error" in resp.get_json()

    def test_404_error_mentions_id(self, client):
        resp = client.get("/api/workflows/no-such-id")
        assert "no-such-id" in resp.get_json()["error"]


# ===========================================================================
# DELETE /api/workflows/<id>
# ===========================================================================

class TestDeleteWorkflow:
    def test_returns_200_on_successful_delete(self, client):
        wf_id = _upload_ok(client)["id"]
        resp = client.delete(f"/api/workflows/{wf_id}")
        assert resp.status_code == 200

    def test_delete_response_has_message(self, client):
        wf_id = _upload_ok(client)["id"]
        body = client.delete(f"/api/workflows/{wf_id}").get_json()
        assert "message" in body

    def test_deleted_workflow_no_longer_in_list(self, client):
        wf_id = _upload_ok(client)["id"]
        client.delete(f"/api/workflows/{wf_id}")
        workflows = client.get("/api/workflows").get_json()
        assert all(w["id"] != wf_id for w in workflows)

    def test_deleted_workflow_returns_404_on_retrieve(self, client):
        wf_id = _upload_ok(client)["id"]
        client.delete(f"/api/workflows/{wf_id}")
        resp = client.get(f"/api/workflows/{wf_id}")
        assert resp.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/workflows/nonexistent-id")
        assert resp.status_code == 404
        assert "error" in resp.get_json()

    def test_delete_only_removes_target(self, client):
        id1 = _upload_ok(client, "a.yaml")["id"]
        id2 = _upload_ok(client, "b.yaml")["id"]
        client.delete(f"/api/workflows/{id1}")
        workflows = client.get("/api/workflows").get_json()
        ids = [w["id"] for w in workflows]
        assert id1 not in ids
        assert id2 in ids


# ===========================================================================
# Storage integration
# ===========================================================================

class TestStorageIntegration:
    def test_file_written_to_disk(self, client, tmp_path, monkeypatch):
        storage_dir = tmp_path / "wf_store"
        monkeypatch.setenv("WORKFLOW_STORAGE_DIR", str(storage_dir))
        import importlib, app.storage.workflow_store as ws
        importlib.reload(ws)
        from app.factory import create_app
        with create_app({"TESTING": True}).test_client() as c:
            body = _upload_ok(c, "wf.yaml")
            wf_id = body["id"]
        stored = list((storage_dir / "files").iterdir())
        assert len(stored) == 1
        assert wf_id in stored[0].name

    def test_index_json_created(self, client, tmp_path, monkeypatch):
        storage_dir = tmp_path / "wf_store"
        monkeypatch.setenv("WORKFLOW_STORAGE_DIR", str(storage_dir))
        import importlib, app.storage.workflow_store as ws
        importlib.reload(ws)
        from app.factory import create_app
        with create_app({"TESTING": True}).test_client() as c:
            _upload_ok(c, "wf.json", VALID_JSON)
        index = json.loads((storage_dir / "index.json").read_text())
        assert len(index) == 1

    def test_file_removed_from_disk_on_delete(self, client, tmp_path, monkeypatch):
        storage_dir = tmp_path / "wf_store"
        monkeypatch.setenv("WORKFLOW_STORAGE_DIR", str(storage_dir))
        import importlib, app.storage.workflow_store as ws
        importlib.reload(ws)
        from app.factory import create_app
        with create_app({"TESTING": True}).test_client() as c:
            wf_id = _upload_ok(c, "wf.yaml")["id"]
            c.delete(f"/api/workflows/{wf_id}")
        stored = list((storage_dir / "files").iterdir())
        assert stored == []
