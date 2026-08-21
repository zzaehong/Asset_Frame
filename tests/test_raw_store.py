import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from asset_frame.domain.models import FetchResponse
from asset_frame.storage.raw import FileRawStore


def test_raw_store_preserves_bytes_hash_and_masked_url(tmp_path: Path) -> None:
    body = b'{"value": 1}'
    snapshot_id = uuid4()
    store = FileRawStore(tmp_path)

    snapshot = store.save(
        snapshot_id=snapshot_id,
        source_id="official-source",
        request_url="https://api.example.test/data?api_key=secret&series=GDP",
        response=FetchResponse(
            status_code=200,
            body=body,
            headers={"Content-Type": "application/json"},
            fetched_at=datetime(2026, 8, 21, tzinfo=UTC),
        ),
    )

    assert snapshot.sha256 == hashlib.sha256(body).hexdigest()
    assert snapshot.request_url.endswith("api_key=%2A%2A%2A&series=GDP")
    assert (tmp_path / snapshot.storage_path).read_bytes() == body
    metadata = json.loads(
        (tmp_path / "official-source" / "snapshots" / f"{snapshot_id}.json").read_text()
    )
    assert metadata["sha256"] == snapshot.sha256
    assert "secret" not in json.dumps(metadata)


def test_same_body_is_content_deduplicated_but_each_fetch_has_metadata(tmp_path: Path) -> None:
    store = FileRawStore(tmp_path)
    response = FetchResponse(200, b"same", {}, datetime(2026, 8, 21, tzinfo=UTC))

    first = store.save(
        snapshot_id=uuid4(), source_id="source", request_url="https://x.test", response=response
    )
    second = store.save(
        snapshot_id=uuid4(), source_id="source", request_url="https://x.test", response=response
    )

    assert first.storage_path == second.storage_path
    assert len(list((tmp_path / "source" / "snapshots").glob("*.json"))) == 2
