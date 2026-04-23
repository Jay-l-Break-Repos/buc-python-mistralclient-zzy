"""
Storage layer for workflow files.

Handles persisting uploaded workflow files to disk and maintaining
a lightweight JSON-based metadata index so the API can look up
workflows by their generated ID without a database dependency.

Record schema (stored in index.json and returned by all public functions)::

    {
        "id":          "<uuid4>",
        "name":        "<original filename>",
        "stored_name": "<id>_<original filename>",
        "size":        <int bytes>,
        "uploaded_at": "<ISO-8601 UTC timestamp>",
    }
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

# Sub-directories / files
FILES_DIR = STORAGE_DIR / "files"
INDEX_FILE = STORAGE_DIR / "index.json"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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
    """Persist the metadata index to disk atomically via a temp-file rename."""
    _ensure_dirs()
    tmp = INDEX_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2)
    tmp.replace(INDEX_FILE)


def _public_record(record: dict) -> dict:
    """Return only the fields that should be exposed in API responses."""
    return {
        "id":          record["id"],
        "name":        record["name"],
        "size":        record["size"],
        "uploaded_at": record["uploaded_at"],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_workflow(filename: str, file_data: bytes) -> dict:
    """
    Persist *file_data* to disk under a unique ID and record its metadata.

    Parameters
    ----------
    filename:
        Original filename supplied by the client.
    file_data:
        Raw bytes of the uploaded file.

    Returns
    -------
    dict
        Public metadata record for the newly stored workflow
        (``id``, ``name``, ``size``, ``uploaded_at``).
    """
    _ensure_dirs()

    workflow_id = str(uuid.uuid4())
    stored_name = f"{workflow_id}_{filename}"
    dest_path = FILES_DIR / stored_name

    dest_path.write_bytes(file_data)

    record = {
        "id":          workflow_id,
        "name":        filename,
        "stored_name": stored_name,
        "size":        len(file_data),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    index = _load_index()
    index[workflow_id] = record
    _save_index(index)

    return _public_record(record)


def list_workflows() -> list:
    """
    Return a list of public metadata records for all stored workflows,
    ordered by ``uploaded_at`` ascending (oldest first).
    """
    index = _load_index()
    records = [_public_record(r) for r in index.values()]
    records.sort(key=lambda r: r["uploaded_at"])
    return records


def get_workflow(workflow_id: str) -> dict | None:
    """
    Return the public metadata record for *workflow_id*, or ``None`` if not
    found.
    """
    index = _load_index()
    record = index.get(workflow_id)
    if record is None:
        return None
    return _public_record(record)


def get_workflow_content(workflow_id: str) -> bytes | None:
    """
    Return the raw file bytes for *workflow_id*, or ``None`` if not found.
    """
    index = _load_index()
    record = index.get(workflow_id)
    if record is None:
        return None
    file_path = FILES_DIR / record["stored_name"]
    if not file_path.exists():
        return None
    return file_path.read_bytes()


def delete_workflow(workflow_id: str) -> bool:
    """
    Remove the stored file and metadata record for *workflow_id*.

    Returns
    -------
    bool
        ``True`` if the workflow existed and was deleted, ``False`` if it
        was not found.
    """
    index = _load_index()
    record = index.get(workflow_id)
    if record is None:
        return False

    # Remove the file (ignore if already missing from disk)
    file_path = FILES_DIR / record["stored_name"]
    try:
        file_path.unlink()
    except FileNotFoundError:
        pass

    del index[workflow_id]
    _save_index(index)
    return True
