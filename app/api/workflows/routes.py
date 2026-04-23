"""
Workflow API endpoints

Routes
------
POST   /api/workflows/upload   – Upload a YAML or JSON workflow file
GET    /api/workflows           – List all uploaded workflows
GET    /api/workflows/<id>      – Retrieve a specific workflow's content
DELETE /api/workflows/<id>      – Delete a workflow

All success and error responses use JSON bodies.
"""

import json

import yaml
from flask import Blueprint, jsonify, request

from app.storage.workflow_store import (
    delete_workflow,
    get_workflow,
    get_workflow_content,
    list_workflows,
    save_workflow,
)

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
    """Return the lower-cased file extension including the leading dot."""
    dot_pos = filename.rfind(".")
    if dot_pos == -1:
        return ""
    return filename[dot_pos:].lower()


def _validate_content(file_bytes: bytes, extension: str) -> str | None:
    """
    Parse *file_bytes* according to *extension*.

    Returns an error message string if the content is malformed, or
    ``None`` if it is valid.
    """
    try:
        if extension in {".yaml", ".yml"}:
            yaml.safe_load(file_bytes)
        else:  # .json
            json.loads(file_bytes)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        return f"File content is not valid {extension.lstrip('.')}: {exc}"
    return None


# ---------------------------------------------------------------------------
# POST /api/workflows/upload
# ---------------------------------------------------------------------------

@workflows_bp.route("/upload", methods=["POST"])
def upload_workflow():
    """
    Upload a YAML or JSON workflow definition file.

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
    # 1. Presence check
    if "file" not in request.files:
        return jsonify({"error": "No file field found in the request. "
                                 "Send the file under the 'file' form field."}), 400

    uploaded_file = request.files["file"]

    if not uploaded_file.filename:
        return jsonify({"error": "No file was selected (filename is empty)."}), 400

    # 2. Extension validation
    filename: str = uploaded_file.filename
    extension = _get_extension(filename)

    if extension not in ALLOWED_EXTENSIONS:
        return jsonify({
            "error": (
                f"Unsupported file type '{extension or '(none)'}'. "
                "Only .yaml, .yml, and .json files are accepted."
            )
        }), 400

    # 3. Content validation
    file_bytes: bytes = uploaded_file.read()

    content_error = _validate_content(file_bytes, extension)
    if content_error:
        return jsonify({"error": content_error}), 400

    # 4. Persist to storage
    try:
        record = save_workflow(filename, file_bytes)
    except OSError as exc:
        return jsonify({"error": f"Failed to save workflow: {exc}"}), 500

    # 5. Return flat record directly (id, name, size, uploaded_at)
    return jsonify(record), 201


# ---------------------------------------------------------------------------
# GET /api/workflows
# ---------------------------------------------------------------------------

@workflows_bp.route("", methods=["GET"])
def list_all_workflows():
    """
    List all uploaded workflows.

    Response 200
    ------------
    A JSON array of workflow metadata objects::

        [
            {
                "id":          "<uuid4>",
                "name":        "<filename>",
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
def retrieve_workflow(workflow_id: str):
    """
    Retrieve a stored workflow's metadata and file content.

    Response 200
    ------------
    ::

        {
            "id":          "<uuid4>",
            "name":        "<filename>",
            "size":        <bytes>,
            "uploaded_at": "<ISO-8601 UTC timestamp>",
            "content":     "<file text as a UTF-8 string>"
        }

    Response 404
    ------------
    ::

        {"error": "Workflow '<id>' not found."}
    """
    record = get_workflow(workflow_id)
    if record is None:
        return jsonify({"error": f"Workflow '{workflow_id}' not found."}), 404

    raw = get_workflow_content(workflow_id)
    if raw is None:
        # Metadata exists but file is missing from disk — treat as not found.
        return jsonify({"error": f"Workflow '{workflow_id}' not found."}), 404

    return jsonify({**record, "content": raw.decode("utf-8")}), 200


# ---------------------------------------------------------------------------
# DELETE /api/workflows/<workflow_id>
# ---------------------------------------------------------------------------

@workflows_bp.route("/<workflow_id>", methods=["DELETE"])
def remove_workflow(workflow_id: str):
    """
    Delete a stored workflow.

    Response 200
    ------------
    ::

        {"message": "Workflow '<id>' deleted successfully."}

    Response 404
    ------------
    ::

        {"error": "Workflow '<id>' not found."}
    """
    deleted = delete_workflow(workflow_id)
    if not deleted:
        return jsonify({"error": f"Workflow '{workflow_id}' not found."}), 404

    return jsonify({"message": f"Workflow '{workflow_id}' deleted successfully."}), 200
