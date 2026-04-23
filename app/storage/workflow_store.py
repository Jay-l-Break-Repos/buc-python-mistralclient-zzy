"""
Storage layer for workflow files.

Handles persisting uploaded workflow files to disk and maintaining
a lightweight JSON-based metadata index so the API can look up
workflows by their generated ID without a database dependency.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Base directory where all workflow files and metadata are stored.
# Defaults to  <repo-root>/workflow_storage  but can be overridden via the
# WORKFLOW_STORAGE_DIR environment variable.
_DEFAULT_STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "workflow_storage"
STORAGE_DIR: Path = Path(os.environ.get("WORKFLOW_STORAGE_DIR", _DEFAULT_STORAGE_DIR))

# Sub-directories
FILES_DIR = STORAGE_DIR / "files"
INDEX_FILE = STORAGE_DIR / "index.json"


def _ensure_dirs() -> None:
    """Create storage directories if they do not already exist."""
    FILES_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> dict:
    """Load the metadata index from disk, returning an empty dict if absent."""
    if INDEX_FILE.exists():
        with INDEX_FILE.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def _save_index(index: dict) -> None:
    """Persist the metadata index to disk atomically."""
    _ensure_dirs()
    tmp = INDEX_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2)
    tmp.replace(INDEX_FILE)


def save_workflow(filename: str, file_data: bytes) -> dict:
    """
    Persist *file_data* to disk under a unique ID and record its metadata.

    Parameters
    ----------
    filename:
        Original filename supplied by the client (used to derive the
        stored filename and to record the extension).
    file_data:
        Raw bytes of the uploaded file.

    Returns
    -------
    dict
        Metadata record for the newly stored workflow::

            {
                "id":          "<uuid4>",
                "filename":    "<original filename>",
                "stored_name": "<id>_<original filename>",
                "size":        <bytes>,
                "uploaded_at": "<ISO-8601 UTC timestamp>",
            }
    """
    _ensure_dirs()

    workflow_id = str(uuid.uuid4())
    stored_name = f"{workflow_id}_{filename}"
    dest_path = FILES_DIR / stored_name

    dest_path.write_bytes(file_data)

    record = {
        "id": workflow_id,
        "filename": filename,
        "stored_name": stored_name,
        "size": len(file_data),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    index = _load_index()
    index[workflow_id] = record
    _save_index(index)

    return record
