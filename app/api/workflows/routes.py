"""
Workflow upload endpoint — POST /api/workflows/upload

Accepts a multipart/form-data request containing a single file field
named ``file``.  The file must have a ``.yaml``, ``.yml``, or ``.json``
extension; any other extension is rejected with HTTP 400.

Valid files are parsed to confirm they are well-formed before being
written to disk via :mod:`app.storage.workflow_store`.

Responses
---------
201 Created
    File accepted and stored successfully.  Body::

        {
            "message": "Workflow uploaded successfully.",
            "workflow": {
                "id":          "<uuid4>",
                "filename":    "<original filename>",
                "size":        <bytes>,
                "uploaded_at": "<ISO-8601 UTC timestamp>"
            }
        }

400 Bad Request
    Returned when:

    * No ``file`` field is present in the request.
    * The filename is empty.
    * The file extension is not ``.yaml``, ``.yml``, or ``.json``.
    * The file content cannot be parsed as valid YAML / JSON.

    Body::

        {"error": "<human-readable message>"}

500 Internal Server Error
    Returned when an unexpected I/O error occurs while saving the file.

    Body::

        {"error": "Failed to save workflow: <detail>"}
"""

import json

import yaml
from flask import Blueprint, jsonify, request

from app.storage.workflow_store import save_workflow

# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

workflows_bp = Blueprint("workflows", __name__, url_prefix="/api/workflows")

# File extensions that are accepted by the upload endpoint.
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
    Parse *file_bytes* according to *extension* and return an error message
    if the content is malformed, or ``None`` if it is valid.
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
# Route
# ---------------------------------------------------------------------------

@workflows_bp.route("/upload", methods=["POST"])
def upload_workflow():
    """
    Upload a YAML or JSON workflow definition file.

    The request must be ``multipart/form-data`` with a field named ``file``
    containing the workflow file.
    """
    # ------------------------------------------------------------------
    # 1. Presence check
    # ------------------------------------------------------------------
    if "file" not in request.files:
        return jsonify({"error": "No file field found in the request. "
                                 "Send the file under the 'file' form field."}), 400

    uploaded_file = request.files["file"]

    if uploaded_file.filename == "" or uploaded_file.filename is None:
        return jsonify({"error": "No file was selected (filename is empty)."}), 400

    # ------------------------------------------------------------------
    # 2. Extension validation
    # ------------------------------------------------------------------
    filename: str = uploaded_file.filename
    extension = _get_extension(filename)

    if extension not in ALLOWED_EXTENSIONS:
        return jsonify({
            "error": (
                f"Unsupported file type '{extension or '(none)'}'. "
                "Only .yaml, .yml, and .json files are accepted."
            )
        }), 400

    # ------------------------------------------------------------------
    # 3. Content validation
    # ------------------------------------------------------------------
    file_bytes: bytes = uploaded_file.read()

    content_error = _validate_content(file_bytes, extension)
    if content_error:
        return jsonify({"error": content_error}), 400

    # ------------------------------------------------------------------
    # 4. Persist to storage
    # ------------------------------------------------------------------
    try:
        record = save_workflow(filename, file_bytes)
    except OSError as exc:
        return jsonify({"error": f"Failed to save workflow: {exc}"}), 500

    # ------------------------------------------------------------------
    # 5. Success response
    # ------------------------------------------------------------------
    response_body = {
        "message": "Workflow uploaded successfully.",
        "workflow": {
            "id":          record["id"],
            "filename":    record["filename"],
            "size":        record["size"],
            "uploaded_at": record["uploaded_at"],
        },
    }
    return jsonify(response_body), 201
