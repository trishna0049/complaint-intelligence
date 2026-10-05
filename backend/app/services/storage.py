"""Attachment storage on local disk (ATTACHMENTS_DIR; a Docker volume in the container setup).

Uploads are streamed to a temporary file while their size and SHA-256 are computed; anything over the size limit is
rejected without being kept. Only an allow-list of document and image types is accepted, and the first bytes must
match the declared type (so an executable can't be uploaded as "invoice.pdf"). Files are stored under a random key —
the user's filename is only ever displayed, never used as a path.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import get_settings

# content type -> (allowed extensions, magic-byte prefixes; empty = text, checked for NUL bytes instead)
ALLOWED: dict[str, tuple[tuple[str, ...], tuple[bytes, ...]]] = {
    "image/png": ((".png",), (b"\x89PNG\r\n\x1a\n",)),
    "image/jpeg": ((".jpg", ".jpeg"), (b"\xff\xd8\xff",)),
    "image/gif": ((".gif",), (b"GIF87a", b"GIF89a")),
    "image/webp": ((".webp",), (b"RIFF",)),
    "application/pdf": ((".pdf",), (b"%PDF-",)),
    "text/plain": ((".txt", ".log"), ()),
    "text/csv": ((".csv",), ()),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ((".docx",), (b"PK\x03\x04",)),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ((".xlsx",), (b"PK\x03\x04",)),
}
CHUNK = 64 * 1024


@dataclass
class StoredFile:
    storage_key: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str


def _root() -> Path:
    root = get_settings().attachments_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_filename(name: str | None) -> str:
    """Display name: no directories, no control characters, at most 120 characters."""
    base = os.path.basename((name or "").replace("\\", "/"))
    base = unicodedata.normalize("NFKC", base)
    base = re.sub(r"[\x00-\x1f\x7f<>:\"/\\|?*]+", "_", base).strip(" .")
    return (base or "attachment")[-120:]


def _reject(message: str, code: int = status.HTTP_422_UNPROCESSABLE_CONTENT) -> HTTPException:
    return HTTPException(code, detail={"code": "invalid_attachment", "message": message})


async def save_upload(upload: UploadFile) -> StoredFile:
    filename = safe_filename(upload.filename)
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    ext = os.path.splitext(filename)[1].lower()
    if content_type not in ALLOWED or ext not in ALLOWED[content_type][0]:
        allowed = ", ".join(sorted({e for exts, _ in ALLOWED.values() for e in exts}))
        raise _reject(f"Unsupported file type. Allowed: {allowed}.", status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    limit = get_settings().max_attachment_mb * 1024 * 1024
    key = secrets.token_hex(16) + ext
    final = _root() / key
    tmp = final.with_suffix(final.suffix + ".part")
    digest, size, head = hashlib.sha256(), 0, b""
    try:
        with tmp.open("wb") as out:
            while chunk := await upload.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise _reject(
                        f"The file is larger than {get_settings().max_attachment_mb} MB.",
                        status.HTTP_413_CONTENT_TOO_LARGE,
                    )
                if len(head) < 16:
                    head += chunk[: 16 - len(head)]
                digest.update(chunk)
                out.write(chunk)
                if not ALLOWED[content_type][1] and b"\x00" in chunk:
                    raise _reject("Text files can't contain binary data.")
        if size == 0:
            raise _reject("The file is empty.")
        signatures = ALLOWED[content_type][1]
        if signatures and not any(head.startswith(sig) for sig in signatures):
            raise _reject("The file's content doesn't match its type.")
        tmp.replace(final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return StoredFile(key, filename, content_type, size, digest.hexdigest())


def path_for(storage_key: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}\.[a-z0-9]{1,5}", storage_key):  # defence in depth: keys are ours
        raise _reject("Invalid attachment key.", status.HTTP_404_NOT_FOUND)
    return _root() / storage_key


def delete(storage_key: str) -> None:
    path_for(storage_key).unlink(missing_ok=True)
