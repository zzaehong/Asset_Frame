"""Hash chain of ledger entries (ADR-0007). Each entry hashes its position, its predecessor's hash,
its type, its payload and its creation time, so changing or removing any entry breaks every later
hash."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass

GENESIS_HASH = "0" * 64


@dataclass(frozen=True, slots=True)
class Entry:
    seq: int
    entry_type: str
    payload: str  # canonical JSON
    created_at: str
    prev_hash: str
    entry_hash: str


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(seq: int, prev_hash: str, entry_type: str, payload: str, created_at: str) -> str:
    material = canonical_json([seq, prev_hash, entry_type, payload, created_at])
    return hashlib.sha256(material.encode()).hexdigest()


def first_broken_seq(entries: Iterable[Entry]) -> int | None:
    """Sequence number of the first entry that does not match the chain; None if intact.

    A deleted entry shows up as a gap in `seq` at the next entry.
    """
    previous_hash, expected_seq = GENESIS_HASH, 1
    for entry in entries:
        recomputed = compute_hash(
            entry.seq, entry.prev_hash, entry.entry_type, entry.payload, entry.created_at
        )
        if (
            entry.seq != expected_seq
            or entry.prev_hash != previous_hash
            or entry.entry_hash != recomputed
        ):
            return entry.seq
        previous_hash, expected_seq = entry.entry_hash, entry.seq + 1
    return None
