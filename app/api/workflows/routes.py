"""
Workflow API endpoints.

Routes
------
POST /api/workflows/upload      – Upload a YAML or JSON workflow definition file.
GET  /api/workflows             – List all uploaded workflow definitions.
GET  /api/workflows/<id>        – Retrieve a specific workflow by ID.

All success and error responses use JSON bodies.
"""

import json

import yaml
from flask import Blueprint, jsonify, request

from app.storage.workflow_store import get_workflow, list_workflows, save_workflow

# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

workflows_bp = Blueprint("workflows", __name__, url_prefix="/api/workflows")

# File extensions accepted by the upload endpoint.
ALLOWED_EXTENSIONS = {".yaml", ".yml", ".json"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_extension(filename: str) -> str:
    """Return the lower-cased file extension including the leading dot.

    Returns an empty string when the filename has no extension.
    """
    dot_pos = filename.rfind(".")
    if dot_pos == -1:
        return ""
    return filename[dot_pos:].lower()


def _validate_content(file_bytes: bytes, extension: str) -> str | None:
    """Parse *file_bytes* according to *extension*.

    Returns an error message string if the content is malformed, or
    ``None`` if it is valid.
    """
    try:
        if extension in {".yaml", ".yml"}:
            yaml.safe_load(file_bytes)
        else:  # .json
            json.loads(file_bytes)
    except yaml.YAMLError as exc:
        return f"File content is not valid yaml: {exc}"
    except json.JSONDecodeError as exc:
        return f"File content is not valid json: {exc}"
    return None


# ---------------------------------------------------------------------------
# POST /api/workflows/upload
# ---------------------------------------------------------------------------

@workflows_bp.route("/upload", methods=["POST"])
def upload_workflow():
    """Upload a YAML or JSON workflow definition file.

    Request
    -------
    ``multipart/form-data`` with a field named ``file``.

    Responses
    ---------
    201
        Workflow stored successfully::

            {
                "id":          "<uuid4>",
                "name":        "<original filename>",
                "size":        <bytes>,
                "uploaded_at": "<ISO-8601 UTC timestamp>"
            }

    400
        Validation failed::

            {"error": "<human-readable message>"}

    500
        Unexpected I/O error while saving::

            {"error": "Failed to save workflow: <detail>"}
    """
    # 1. Presence check -------------------------------------------------------
    if "file" not in request.files:
        return jsonify(
            {"error": "No file field found in the request. "
                      "Send the file under the 'file' form field."}
        ), 400

    uploaded_file = request.files["file"]

    if not uploaded_file.filename:
        return jsonify({"error": "No file was selected (filename is empty)."}), 400

    # 2. Extension validation -------------------------------------------------
    filename: str = uploaded_file.filename
    extension = _get_extension(filename)

    if extension not in ALLOWED_EXTENSIONS:
        return jsonify(
            {
                "error": (
                    f"Unsupported file type '{extension or '(none)'}'. "
                    "Only .yaml, .yml, and .json files are accepted."
                )
            }
        ), 400

    # 3. Content validation ---------------------------------------------------
    file_bytes: bytes = uploaded_file.read()

    content_error = _validate_content(file_bytes, extension)
    if content_error:
        return jsonify({"error": content_error}), 400

    # 4. Persist to storage ---------------------------------------------------
    try:
        record = save_workflow(filename, file_bytes)
    except OSError as exc:
        return jsonify({"error": f"Failed to save workflow: {exc}"}), 500

    # 5. Return flat record (id, name, size, uploaded_at) --------------------
    return jsonify(record), 201


# ---------------------------------------------------------------------------
# GET /api/workflows
# ---------------------------------------------------------------------------

@workflows_bp.route("", methods=["GET"])
def list_workflows_endpoint():
    """List all uploaded workflow definitions.

    Responses
    ---------
    200
        JSON array of workflow metadata records (may be empty)::

            [
                {
                    "id":          "<uuid4>",
                    "name":        "<original filename>",
                    "size":        <bytes>,
                    "uploaded_at": "<ISO-8601 UTC timestamp>"
                },
                ...
            ]
    """
    workflows = list_workflows()
    return jsonify(workflows), 200


# ---------------------------------------------------------------------------
# GET /api/workflows/<workflow_id>
# ---------------------------------------------------------------------------

@workflows_bp.route("/<workflow_id>", methods=["GET"])
def get_workflow_endpoint(workflow_id: str):
    """Retrieve a specific workflow by its ID.

    Path parameters
    ---------------
    workflow_id:
        The UUID string returned when the workflow was uploaded.

    Responses
    ---------
    200
        Workflow metadata plus parsed content::

            {
                "id":          "<uuid4>",
                "name":        "<original filename>",
                "size":        <bytes>,
                "uploaded_at": "<ISO-8601 UTC timestamp>",
                "content":     { ... }   ← parsed YAML/JSON as a JSON object
            }

    404
        No workflow with the given ID exists::

            {"error": "Workflow '<id>' not found."}

    500
        Unexpected I/O error while reading the stored file::

            {"error": "Failed to read workflow: <detail>"}
    """
    try:
        record = get_workflow(workflow_id)
    except OSError as exc:
        return jsonify({"error": f"Failed to read workflow: {exc}"}), 500

    if record is None:
        return jsonify({"error": f"Workflow '{workflow_id}' not found."}), 404

    return jsonify(record), 200
