"""
Storage layer for workflow files.

Handles persisting uploaded workflow files to disk and maintaining a
lightweight JSON-based metadata index so the API can look up workflows
by their generated ID without a database dependency.

Directory layout
----------------
::

    <STORAGE_DIR>/
        files/          ← raw uploaded files, named  <uuid>_<original-name>
        index.json      ← JSON object mapping workflow ID → metadata record

Record schema (stored in ``index.json`` and returned by all public functions)::

    {
        "id":          "<uuid4>",
        "name":        "<original filename>",
        "stored_name": "<id>_<original filename>",
        "size":        <int bytes>,
        "uploaded_at": "<ISO-8601 UTC timestamp>",
    }

The ``WORKFLOW_STORAGE_DIR`` environment variable overrides the default
storage location, which is ``uploads/workflows/`` relative to the
repository root.  Tests use this variable to point at a temporary
directory so they remain fully isolated.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Storage paths
# ---------------------------------------------------------------------------

# Default: <repo-root>/uploads/workflows
_DEFAULT_STORAGE_DIR = (
    Path(__file__).resolve().parent.parent.parent / "uploads" / "workflows"
)

STORAGE_DIR: Path = Path(
    os.environ.get("WORKFLOW_STORAGE_DIR", _DEFAULT_STORAGE_DIR)
)

FILES_DIR: Path = STORAGE_DIR / "files"
INDEX_FILE: Path = STORAGE_DIR / "index.json"


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

def list_workflows() -> list:
    """Return a list of all stored workflow metadata records.

    Records are sorted by ``uploaded_at`` in ascending order (oldest first)
    so the list is deterministic regardless of insertion order in the index.

    Returns
    -------
    list[dict]
        A (possibly empty) list of public metadata records, each containing
        ``id``, ``name``, ``size``, and ``uploaded_at``.
    """
    index = _load_index()
    records = [_public_record(r) for r in index.values()]
    records.sort(key=lambda r: r["uploaded_at"])
    return records


def save_workflow(filename: str, file_data: bytes) -> dict:
    """Persist *file_data* to disk under a unique ID and record its metadata.

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

    Raises
    ------
    OSError
        If the file cannot be written to disk.
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
