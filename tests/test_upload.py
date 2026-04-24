"""
Tests for POST /api/workflows/upload

Covers
------
- Happy-path uploads for .yaml, .yml, and .json files
- Response shape validation (id, name, size, uploaded_at)
- Validation errors (missing file, empty filename, bad extension)
- Content validation errors (malformed YAML / JSON)
- Storage integration (file written to disk, index.json created)
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
# POST /api/workflows/upload  –  happy path
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


# ===========================================================================
# POST /api/workflows/upload  –  validation errors
# ===========================================================================

class TestUploadValidationErrors:
    def test_missing_file_field_returns_400(self, client):
        resp = client.post(
            "/api/workflows/upload", data={}, content_type="multipart/form-data"
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_empty_filename_returns_400(self, client):
        data = {"file": (io.BytesIO(VALID_YAML), "")}
        resp = client.post(
            "/api/workflows/upload", data=data, content_type="multipart/form-data"
        )
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
# Storage integration
# ===========================================================================

class TestStorageIntegration:
    def test_file_written_to_disk(self, tmp_path, monkeypatch):
        storage_dir = tmp_path / "wf_store"
        monkeypatch.setenv("WORKFLOW_STORAGE_DIR", str(storage_dir))
        import importlib
        import app.storage.workflow_store as ws
        importlib.reload(ws)
        from app.factory import create_app
        with create_app({"TESTING": True}).test_client() as c:
            body = _upload_ok(c, "wf.yaml")
            wf_id = body["id"]
        stored = list((storage_dir / "files").iterdir())
        assert len(stored) == 1
        assert wf_id in stored[0].name

    def test_index_json_created(self, tmp_path, monkeypatch):
        storage_dir = tmp_path / "wf_store"
        monkeypatch.setenv("WORKFLOW_STORAGE_DIR", str(storage_dir))
        import importlib
        import app.storage.workflow_store as ws
        importlib.reload(ws)
        from app.factory import create_app
        with create_app({"TESTING": True}).test_client() as c:
            _upload_ok(c, "wf.json", VALID_JSON)
        index = json.loads((storage_dir / "index.json").read_text())
        assert len(index) == 1
