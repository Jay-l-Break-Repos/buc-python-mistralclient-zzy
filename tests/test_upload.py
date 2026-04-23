"""
Tests for POST /api/workflows/upload

Covers:
- Successful YAML upload (.yaml and .yml)
- Successful JSON upload (.json)
- Missing file field → 400
- Empty filename → 400
- Unsupported extension → 400
- Malformed YAML content → 400
- Malformed JSON content → 400
"""

import io
import json
import os
import tempfile

import pytest

# Point storage at a temp directory so tests don't pollute the repo.
@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKFLOW_STORAGE_DIR", str(tmp_path / "workflow_storage"))
    # Re-import storage module so it picks up the new env var.
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
# Helpers
# ---------------------------------------------------------------------------

def _upload(client, filename: str, content: bytes, field: str = "file"):
    """Send a multipart upload request."""
    data = {field: (io.BytesIO(content), filename)}
    return client.post(
        "/api/workflows/upload",
        data=data,
        content_type="multipart/form-data",
    )


VALID_YAML = b"version: '2.0'\nname: my_workflow\ntasks:\n  task1:\n    action: std.noop\n"
VALID_JSON = b'{"version": "2.0", "name": "my_workflow"}'


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

class TestSuccessfulUploads:
    def test_upload_yaml_extension(self, client):
        resp = _upload(client, "workflow.yaml", VALID_YAML)
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["message"] == "Workflow uploaded successfully."
        wf = body["workflow"]
        assert wf["filename"] == "workflow.yaml"
        assert "id" in wf
        assert wf["size"] == len(VALID_YAML)
        assert "uploaded_at" in wf

    def test_upload_yml_extension(self, client):
        resp = _upload(client, "workflow.yml", VALID_YAML)
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["workflow"]["filename"] == "workflow.yml"

    def test_upload_json_extension(self, client):
        resp = _upload(client, "workflow.json", VALID_JSON)
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["workflow"]["filename"] == "workflow.json"

    def test_each_upload_gets_unique_id(self, client):
        r1 = _upload(client, "wf.yaml", VALID_YAML)
        r2 = _upload(client, "wf.yaml", VALID_YAML)
        id1 = r1.get_json()["workflow"]["id"]
        id2 = r2.get_json()["workflow"]["id"]
        assert id1 != id2

    def test_response_contains_size(self, client):
        resp = _upload(client, "wf.json", VALID_JSON)
        assert resp.get_json()["workflow"]["size"] == len(VALID_JSON)


# ---------------------------------------------------------------------------
# Validation error tests
# ---------------------------------------------------------------------------

class TestValidationErrors:
    def test_missing_file_field_returns_400(self, client):
        resp = client.post("/api/workflows/upload", data={}, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_empty_filename_returns_400(self, client):
        data = {"file": (io.BytesIO(VALID_YAML), "")}
        resp = client.post(
            "/api/workflows/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_unsupported_extension_txt_returns_400(self, client):
        resp = _upload(client, "workflow.txt", VALID_YAML)
        assert resp.status_code == 400
        body = resp.get_json()
        assert "error" in body
        assert ".txt" in body["error"]

    def test_unsupported_extension_xml_returns_400(self, client):
        resp = _upload(client, "workflow.xml", b"<root/>")
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_no_extension_returns_400(self, client):
        resp = _upload(client, "workflow", VALID_YAML)
        assert resp.status_code == 400
        body = resp.get_json()
        assert "error" in body

    def test_malformed_yaml_returns_400(self, client):
        bad_yaml = b"key: [unclosed bracket\n  - item\n"
        resp = _upload(client, "bad.yaml", bad_yaml)
        assert resp.status_code == 400
        body = resp.get_json()
        assert "error" in body
        assert "yaml" in body["error"].lower()

    def test_malformed_json_returns_400(self, client):
        bad_json = b'{"key": "value", "broken":'
        resp = _upload(client, "bad.json", bad_json)
        assert resp.status_code == 400
        body = resp.get_json()
        assert "error" in body
        assert "json" in body["error"].lower()

    def test_error_message_mentions_allowed_types(self, client):
        resp = _upload(client, "workflow.csv", b"a,b,c")
        body = resp.get_json()
        error_msg = body["error"].lower()
        assert "yaml" in error_msg or "yml" in error_msg or "json" in error_msg


# ---------------------------------------------------------------------------
# Storage integration tests
# ---------------------------------------------------------------------------

class TestStorageIntegration:
    def test_file_is_written_to_disk(self, client, tmp_path, monkeypatch):
        storage_dir = tmp_path / "workflow_storage"
        monkeypatch.setenv("WORKFLOW_STORAGE_DIR", str(storage_dir))

        import importlib
        import app.storage.workflow_store as ws
        importlib.reload(ws)

        # Re-create client with fresh storage
        from app.factory import create_app
        app = create_app({"TESTING": True})
        with app.test_client() as c:
            resp = _upload(c, "wf.yaml", VALID_YAML)
            assert resp.status_code == 201
            wf_id = resp.get_json()["workflow"]["id"]

        files_dir = storage_dir / "files"
        stored_files = list(files_dir.iterdir())
        assert len(stored_files) == 1
        assert wf_id in stored_files[0].name

    def test_index_json_is_created(self, client, tmp_path, monkeypatch):
        storage_dir = tmp_path / "workflow_storage"
        monkeypatch.setenv("WORKFLOW_STORAGE_DIR", str(storage_dir))

        import importlib
        import app.storage.workflow_store as ws
        importlib.reload(ws)

        from app.factory import create_app
        app = create_app({"TESTING": True})
        with app.test_client() as c:
            _upload(c, "wf.json", VALID_JSON)

        index_file = storage_dir / "index.json"
        assert index_file.exists()
        index = json.loads(index_file.read_text())
        assert len(index) == 1
