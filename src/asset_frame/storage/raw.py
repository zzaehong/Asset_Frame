from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Protocol
from uuid import UUID

from asset_frame.domain.models import FetchResponse, RawSnapshot
from asset_frame.ingestion.security import mask_url_secrets


class RawStore(Protocol):
    def save(
        self,
        *,
        snapshot_id: UUID,
        source_id: str,
        request_url: str,
        response: FetchResponse,
    ) -> RawSnapshot: ...


class FileRawStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def save(
        self,
        *,
        snapshot_id: UUID,
        source_id: str,
        request_url: str,
        response: FetchResponse,
    ) -> RawSnapshot:
        digest = hashlib.sha256(response.body).hexdigest()
        relative_path = Path(source_id) / digest[:2] / f"{digest}.bin"
        body_path = self._root / relative_path
        metadata_path = self._root / source_id / "snapshots" / f"{snapshot_id}.json"
        body_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)

        self._write_once(body_path, response.body)
        snapshot = RawSnapshot(
            id=snapshot_id,
            source_id=source_id,
            request_url=mask_url_secrets(request_url),
            fetched_at=response.fetched_at,
            http_status=response.status_code,
            content_type=response.headers.get("Content-Type"),
            content_length=len(response.body),
            sha256=digest,
            storage_path=str(relative_path),
        )
        metadata = asdict(snapshot)
        metadata["id"] = str(snapshot.id)
        metadata["fetched_at"] = snapshot.fetched_at.isoformat()
        self._write_once(
            metadata_path,
            json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        )
        return snapshot

    @staticmethod
    def _write_once(path: Path, content: bytes) -> None:
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o440)
        except FileExistsError:
            if path.read_bytes() != content:
                raise RuntimeError(f"immutable raw path collision: {path}") from None
            return
        with os.fdopen(descriptor, "wb") as raw_file:
            raw_file.write(content)
            raw_file.flush()
            os.fsync(raw_file.fileno())
