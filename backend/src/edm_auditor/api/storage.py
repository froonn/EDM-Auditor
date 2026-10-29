"""Safe local storage for uploaded documents."""

from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile


async def store_upload(
    upload: UploadFile, directory: Path, max_bytes: int
) -> tuple[Path, int]:
    directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.filename or "").suffix.lower()
    target = directory / f"{uuid4().hex}{suffix}"
    total = 0
    try:
        with target.open("wb") as destination:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Uploaded file exceeds the configured size limit")
                destination.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return target, total
