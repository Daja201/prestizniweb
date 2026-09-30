# storage.py - safe, traversal-proof, atomic file storage under UPLOAD_DIR
import os
import re
import uuid
from pathlib import Path

from app.core.config import settings

_EXT_RE = re.compile(r"^[a-z0-9]{1,5}$")


def _upload_root() -> Path:
    return Path(settings.upload_dir).resolve()


def abs_path(rel_path: str) -> Path:
    """Resolve a relative storage path to an absolute path, rejecting traversal."""
    root = _upload_root()
    candidate = (root / rel_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path traversal rejected: {rel_path!r}")
    return candidate


def save_bytes(subdir: str, data: bytes, ext: str) -> str:
    """Save bytes under a random, sharded, unguessable name. Returns the relative path."""
    if not _EXT_RE.match(ext):
        raise ValueError(f"invalid extension: {ext!r}")

    name = uuid.uuid4().hex
    shard = name[:2]
    rel_path = f"{subdir}/{shard}/{name}.{ext}"
    target = abs_path(rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = target.with_suffix(target.suffix + ".tmp")
    with open(tmp_path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, target)

    return rel_path


def delete(rel_path: str | None) -> None:
    """Delete a stored file, silently ignoring a missing file or empty path."""
    if not rel_path:
        return
    try:
        path = abs_path(rel_path)
    except ValueError:
        return
    path.unlink(missing_ok=True)