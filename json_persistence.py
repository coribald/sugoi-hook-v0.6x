"""Small, durable JSON persistence helpers for local application state."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable


class JsonPersistenceError(RuntimeError):
    """Raised when a persisted JSON object cannot be loaded safely."""


JsonValidator = Callable[[dict[str, Any]], bool]


def backup_path_for(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


def _read_object(path: Path, validator: JsonValidator | None) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise JsonPersistenceError("top-level JSON value must be an object")
    if validator is not None and not validator(value):
        raise JsonPersistenceError("JSON object has an unsupported shape")
    return value


def load_json_object(path: Path, validator: JsonValidator | None = None) -> tuple[dict[str, Any] | None, bool]:
    """Load an object, falling back to its last valid ``.bak`` copy.

    Returns ``(value, recovered_from_backup)``.  A missing primary file is not
    an error; malformed primary and backup files raise ``JsonPersistenceError``.
    """
    path = Path(path)
    if not path.exists():
        return None, False

    try:
        return _read_object(path, validator), False
    except (OSError, json.JSONDecodeError, JsonPersistenceError) as primary_error:
        backup_path = backup_path_for(path)
        if backup_path.exists():
            try:
                return _read_object(backup_path, validator), True
            except (OSError, json.JSONDecodeError, JsonPersistenceError) as backup_error:
                raise JsonPersistenceError(
                    f"could not load {path.name} ({primary_error}); backup also failed ({backup_error})"
                ) from backup_error
        raise JsonPersistenceError(f"could not load {path.name}: {primary_error}") from primary_error


def save_json_object_atomic(path: Path, value: dict[str, Any], validator: JsonValidator | None = None) -> None:
    """Durably replace a JSON config without risking the existing file.

    The old file is copied to ``.bak`` only after it has been verified as a
    valid object.  The replacement is written and flushed in the same
    directory so ``os.replace`` remains atomic on Windows.
    """
    if not isinstance(value, dict):
        raise JsonPersistenceError("top-level JSON value must be an object")
    if validator is not None and not validator(value):
        raise JsonPersistenceError("refusing to save JSON object with an unsupported shape")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        if path.exists():
            try:
                _read_object(path, validator)
            except (OSError, json.JSONDecodeError, JsonPersistenceError):
                pass
            else:
                shutil.copy2(path, backup_path_for(path))

        os.replace(temporary_path, path)
    except (OSError, TypeError, ValueError) as error:
        raise JsonPersistenceError(f"could not save {path.name}: {error}") from error
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
