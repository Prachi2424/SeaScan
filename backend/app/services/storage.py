from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import Settings

SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class StoredUpload:
    original_filename: str
    stored_filename: str
    path: Path
    byte_size: int
    sha256: str


async def store_upload(upload: UploadFile, settings: Settings, category: str) -> StoredUpload:
    """Stream an upload to disk while calculating its integrity hash and enforcing a size limit."""
    original_filename = upload.filename or "unnamed"
    suffix = Path(original_filename).suffix.lower()
    safe_stem = SAFE_FILENAME.sub("_", Path(original_filename).stem).strip("._") or "evidence"
    stored_filename = f"{uuid.uuid4()}_{safe_stem[:80]}{suffix}"
    destination_directory = settings.project_data_directories[0] / category
    destination_directory.mkdir(parents=True, exist_ok=True)
    destination = destination_directory / stored_filename
    maximum_bytes = settings.max_upload_size_mb * 1024 * 1024
    digest = hashlib.sha256()
    bytes_written = 0
    try:
        with destination.open("xb") as destination_file:
            while chunk := await upload.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > maximum_bytes:
                    destination_file.close()
                    destination.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Upload exceeds the {settings.max_upload_size_mb} MB limit.",
                    )
                digest.update(chunk)
                destination_file.write(chunk)
    except HTTPException:
        raise
    except Exception as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to persist uploaded evidence.") from error
    finally:
        await upload.close()
    if bytes_written == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Empty uploads are not valid evidence.")
    return StoredUpload(original_filename, stored_filename, destination, bytes_written, digest.hexdigest())


def discard_upload(stored_upload: StoredUpload) -> None:
    stored_upload.path.unlink(missing_ok=True)
