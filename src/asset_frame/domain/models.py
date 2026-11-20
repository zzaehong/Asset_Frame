from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID


class AccessMethod(StrEnum):
    OFFICIAL_API = "official_api"
    OFFICIAL_BULK = "official_bulk"
    OFFICIAL_DOWNLOAD = "official_download"


class AuthorityType(StrEnum):
    REGULATOR = "regulator"
    EXCHANGE = "exchange"
    CENTRAL_BANK = "central_bank"
    GOVERNMENT = "government"
    DOCUMENTED_PROVIDER = "documented_provider"


class SourceRole(StrEnum):
    PRIMARY = "primary"
    VALIDATION = "validation"
    FALLBACK = "fallback"
    VERIFICATION = "verification"


class ImplementationStatus(StrEnum):
    AVAILABLE = "available"
    PLANNED = "planned"


class DataKind(StrEnum):
    ASSET_IDENTIFIER = "asset_identifier"
    PRICE = "price"
    CORPORATE_ACTION = "corporate_action"
    MACRO = "macro"


class IngestionStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class QualityStatus(StrEnum):
    ACCEPTED = "accepted"
    QUARANTINED = "quarantined"


class AssetType(StrEnum):
    EQUITY = "equity"
    ETF = "etf"
    MUTUAL_FUND = "mutual_fund"


class IdentifierType(StrEnum):
    TICKER = "ticker"
    ISIN = "isin"
    EXCHANGE_CODE = "exchange_code"


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    id: str
    authority: str
    authority_type: AuthorityType
    access_method: AccessMethod
    role: SourceRole
    data_kinds: tuple[DataKind, ...]
    documentation_url: str
    terms_url: str
    verification_url: str
    enabled: bool
    implementation_status: ImplementationStatus


@dataclass(frozen=True, slots=True)
class FetchRequest:
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class FetchResponse:
    status_code: int
    body: bytes
    headers: dict[str, str]
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class RawSnapshot:
    id: UUID
    source_id: str
    request_url: str
    fetched_at: datetime
    http_status: int
    content_type: str | None
    content_length: int
    sha256: str
    storage_path: str
    ingestion_run_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Asset:
    id: UUID
    name: str
    asset_type: AssetType
    country_code: str
    currency: str


@dataclass(frozen=True, slots=True)
class AssetIdentifier:
    asset_id: UUID
    identifier_type: IdentifierType
    value: str
    valid_from: date | None = None
    valid_to: date | None = None


@dataclass(frozen=True, slots=True)
class PriceObservation:
    asset_id: UUID
    source_id: str
    raw_snapshot_id: UUID
    trading_date: date
    currency: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    adjusted_close: Decimal | None
    volume: Decimal | None
    fetched_at: datetime
    price_basis: str
    quality_status: QualityStatus = QualityStatus.ACCEPTED


@dataclass(frozen=True, slots=True)
class CorporateAction:
    asset_id: UUID
    source_id: str
    raw_snapshot_id: UUID
    action_type: str
    effective_at: date
    announced_at: datetime | None
    amount: Decimal | None = None
    currency: str | None = None
    ratio_numerator: Decimal | None = None
    ratio_denominator: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QuarantinedPrice:
    price: PriceObservation
    issue_code: str
    details: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MacroObservation:
    source_id: str
    raw_snapshot_id: UUID
    series_id: str
    observation_date: date
    value: Decimal | None
    realtime_start: date
    realtime_end: date
    fetched_at: datetime
