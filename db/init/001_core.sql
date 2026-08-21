CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE source_access_method AS ENUM ('official_api', 'official_bulk', 'official_download');
CREATE TYPE source_authority_type AS ENUM (
    'regulator', 'exchange', 'central_bank', 'government', 'documented_provider'
);
CREATE TYPE source_role AS ENUM ('primary', 'validation', 'fallback', 'verification');
CREATE TYPE implementation_status AS ENUM ('available', 'planned');
CREATE TYPE ingestion_status AS ENUM ('started', 'succeeded', 'failed');
CREATE TYPE quality_status AS ENUM ('accepted', 'quarantined');
CREATE TYPE asset_type AS ENUM ('equity', 'etf');
CREATE TYPE identifier_type AS ENUM ('ticker', 'isin', 'cik', 'dart_corp_code', 'exchange_code');

CREATE TABLE sources (
    source_id text PRIMARY KEY,
    authority text NOT NULL,
    authority_type source_authority_type NOT NULL,
    access_method source_access_method NOT NULL,
    source_role source_role NOT NULL,
    data_kinds text[] NOT NULL,
    documentation_url text NOT NULL,
    terms_url text NOT NULL,
    verification_url text NOT NULL,
    enabled boolean NOT NULL,
    implementation_status implementation_status NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (cardinality(data_kinds) > 0)
);

CREATE TABLE ingestion_runs (
    ingestion_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id text NOT NULL REFERENCES sources(source_id),
    data_kind text NOT NULL,
    status ingestion_status NOT NULL DEFAULT 'started',
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    records_received integer NOT NULL DEFAULT 0 CHECK (records_received >= 0),
    records_accepted integer NOT NULL DEFAULT 0 CHECK (records_accepted >= 0),
    records_quarantined integer NOT NULL DEFAULT 0 CHECK (records_quarantined >= 0),
    error_code text,
    error_message text,
    CHECK ((status = 'started' AND finished_at IS NULL) OR
           (status <> 'started' AND finished_at IS NOT NULL))
);

CREATE TABLE raw_snapshots (
    raw_snapshot_id uuid PRIMARY KEY,
    ingestion_run_id uuid REFERENCES ingestion_runs(ingestion_run_id),
    source_id text NOT NULL REFERENCES sources(source_id),
    request_url text NOT NULL,
    fetched_at timestamptz NOT NULL,
    http_status integer NOT NULL CHECK (http_status BETWEEN 100 AND 599),
    content_type text,
    content_length bigint NOT NULL CHECK (content_length >= 0),
    sha256 char(64) NOT NULL,
    storage_path text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE assets (
    asset_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    asset_type asset_type NOT NULL,
    country_code char(2) NOT NULL,
    currency char(3) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE asset_identifiers (
    asset_id uuid NOT NULL REFERENCES assets(asset_id),
    identifier_type identifier_type NOT NULL,
    identifier_value text NOT NULL,
    valid_from date,
    valid_to date,
    PRIMARY KEY (asset_id, identifier_type, identifier_value),
    UNIQUE (identifier_type, identifier_value, valid_from),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);

CREATE TABLE price_observations (
    asset_id uuid NOT NULL REFERENCES assets(asset_id),
    source_id text NOT NULL REFERENCES sources(source_id),
    raw_snapshot_id uuid NOT NULL REFERENCES raw_snapshots(raw_snapshot_id),
    trading_date date NOT NULL,
    currency char(3) NOT NULL,
    open numeric,
    high numeric,
    low numeric,
    close numeric NOT NULL,
    adjusted_close numeric,
    volume numeric,
    price_basis text NOT NULL,
    fetched_at timestamptz NOT NULL,
    quality_status quality_status NOT NULL DEFAULT 'accepted',
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz,
    PRIMARY KEY (asset_id, source_id, trading_date, price_basis, valid_from),
    CHECK (close > 0 AND (open IS NULL OR open > 0) AND (high IS NULL OR high > 0)
           AND (low IS NULL OR low > 0) AND (adjusted_close IS NULL OR adjusted_close > 0)),
    CHECK (volume IS NULL OR volume >= 0),
    CHECK (high IS NULL OR low IS NULL OR high >= low),
    CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE TABLE corporate_actions (
    corporate_action_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id uuid NOT NULL REFERENCES assets(asset_id),
    source_id text NOT NULL REFERENCES sources(source_id),
    raw_snapshot_id uuid NOT NULL REFERENCES raw_snapshots(raw_snapshot_id),
    action_type text NOT NULL,
    effective_at date NOT NULL,
    announced_at timestamptz,
    amount numeric,
    currency char(3),
    ratio_numerator numeric,
    ratio_denominator numeric,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE financial_facts (
    financial_fact_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id uuid NOT NULL REFERENCES assets(asset_id),
    source_id text NOT NULL REFERENCES sources(source_id),
    raw_snapshot_id uuid NOT NULL REFERENCES raw_snapshots(raw_snapshot_id),
    taxonomy text NOT NULL,
    concept text NOT NULL,
    unit text NOT NULL,
    value numeric NOT NULL,
    period_start date,
    period_end date NOT NULL,
    filed_at timestamptz NOT NULL,
    published_at timestamptz,
    revised_at timestamptz,
    accession_number text,
    dimensions jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE filing_documents (
    filing_document_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id uuid NOT NULL REFERENCES assets(asset_id),
    source_id text NOT NULL REFERENCES sources(source_id),
    raw_snapshot_id uuid NOT NULL REFERENCES raw_snapshots(raw_snapshot_id),
    accession_number text NOT NULL,
    form_type text NOT NULL,
    report_period date,
    filed_at date NOT NULL,
    published_at timestamptz,
    primary_document text,
    document_url text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_id, accession_number)
);

CREATE TABLE etf_holdings (
    etf_asset_id uuid NOT NULL REFERENCES assets(asset_id),
    component_asset_id uuid REFERENCES assets(asset_id),
    source_id text NOT NULL REFERENCES sources(source_id),
    raw_snapshot_id uuid NOT NULL REFERENCES raw_snapshots(raw_snapshot_id),
    as_of_date date NOT NULL,
    component_name text NOT NULL,
    component_identifier text,
    weight numeric,
    quantity numeric,
    market_value numeric,
    currency char(3),
    published_at timestamptz,
    PRIMARY KEY (etf_asset_id, source_id, as_of_date, component_name, raw_snapshot_id),
    CHECK (weight IS NULL OR (weight >= 0 AND weight <= 1))
);

CREATE TABLE macro_observations (
    source_id text NOT NULL REFERENCES sources(source_id),
    raw_snapshot_id uuid NOT NULL REFERENCES raw_snapshots(raw_snapshot_id),
    series_id text NOT NULL,
    observation_date date NOT NULL,
    value numeric,
    unit text NOT NULL,
    frequency text NOT NULL,
    published_at timestamptz,
    revised_at timestamptz,
    fetched_at timestamptz NOT NULL,
    PRIMARY KEY (source_id, series_id, observation_date, raw_snapshot_id)
);

CREATE TABLE quality_issues (
    quality_issue_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ingestion_run_id uuid REFERENCES ingestion_runs(ingestion_run_id),
    raw_snapshot_id uuid REFERENCES raw_snapshots(raw_snapshot_id),
    asset_id uuid REFERENCES assets(asset_id),
    issue_code text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('warning', 'error')),
    status quality_status NOT NULL DEFAULT 'quarantined',
    details jsonb NOT NULL,
    detected_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    resolution text
);

CREATE INDEX price_observations_asset_date_idx
    ON price_observations (asset_id, trading_date DESC);
CREATE INDEX financial_facts_asset_period_idx
    ON financial_facts (asset_id, period_end DESC);
CREATE INDEX filing_documents_asset_filed_idx
    ON filing_documents (asset_id, filed_at DESC);
CREATE INDEX raw_snapshots_source_fetched_idx
    ON raw_snapshots (source_id, fetched_at DESC);
