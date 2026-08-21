from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


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
    FINANCIAL_FACT = "financial_fact"
    FILING = "filing"
    ETF_HOLDING = "etf_holding"
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


class IdentifierType(StrEnum):
    TICKER = "ticker"
    ISIN = "isin"
    CIK = "cik"
    DART_CORP_CODE = "dart_corp_code"
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
class RegulatoryIdentifierRecord:
    ticker: str
    name: str
    identifier_type: IdentifierType
    identifier_value: str
    exchange_code: str | None = None
    modified_at: date | None = None


@dataclass(frozen=True, slots=True)
class FilingDocument:
    asset_id: UUID
    source_id: str
    raw_snapshot_id: UUID
    accession_number: str
    form_type: str
    filed_at: date
    published_at: datetime | None
    report_period: date | None
    primary_document: str | None
    document_url: str
    metadata: dict[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)


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
class FinancialFact:
    asset_id: UUID
    source_id: str
    raw_snapshot_id: UUID
    taxonomy: str
    concept: str
    unit: str
    value: Decimal
    period_start: date | None
    period_end: date
    filed_at: datetime
    published_at: datetime | None
    revised_at: datetime | None
    accession_number: str | None
    dimensions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EtfHolding:
    etf_asset_id: UUID
    component_asset_id: UUID | None
    source_id: str
    raw_snapshot_id: UUID
    as_of_date: date
    component_name: str
    component_identifier: str | None
    weight: Decimal | None
    quantity: Decimal | None
    market_value: Decimal | None
    currency: str | None
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class MacroObservation:
    source_id: str
    raw_snapshot_id: UUID
    series_id: str
    observation_date: date
    value: Decimal | None
    unit: str
    frequency: str
    published_at: datetime | None
    revised_at: datetime | None
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class QuarantinedPrice:
    price: PriceObservation
    issue_code: str
    details: dict[str, Any]
