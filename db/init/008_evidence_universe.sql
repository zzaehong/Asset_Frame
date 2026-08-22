CREATE TABLE etf_exposures (
    exposure_key text PRIMARY KEY,
    asset_class text NOT NULL,
    region text NOT NULL,
    role text NOT NULL,
    benchmark_name text,
    risk_group text NOT NULL DEFAULT 'core'
        CHECK (risk_group IN ('core', 'high_risk')),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE etf_universe_catalog (
    etf_asset_id uuid NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    exposure_key text NOT NULL REFERENCES etf_exposures(exposure_key),
    selected_rank integer NOT NULL CHECK (selected_rank > 0),
    policy_version integer NOT NULL CHECK (policy_version > 0),
    valid_from date NOT NULL,
    valid_to date,
    selection_reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (etf_asset_id, valid_from),
    CHECK (valid_to IS NULL OR valid_from <= valid_to)
);

CREATE INDEX etf_universe_catalog_active_idx
    ON etf_universe_catalog (selected_rank, etf_asset_id)
    WHERE valid_to IS NULL;

CREATE INDEX etf_universe_catalog_exposure_idx
    ON etf_universe_catalog (exposure_key, valid_from, valid_to);

CREATE TABLE tracked_investment_managers (
    investment_manager_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sec_cik char(10) NOT NULL UNIQUE CHECK (sec_cik ~ '^[0-9]{10}$'),
    name text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE manager_13f_filings (
    manager_13f_filing_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    investment_manager_id uuid NOT NULL
        REFERENCES tracked_investment_managers(investment_manager_id) ON DELETE CASCADE,
    source_id text NOT NULL REFERENCES sources(source_id),
    raw_snapshot_id uuid NOT NULL REFERENCES raw_snapshots(raw_snapshot_id),
    accession_number text NOT NULL UNIQUE,
    form_type text NOT NULL CHECK (form_type IN ('13F-HR', '13F-HR/A')),
    report_period date NOT NULL,
    filed_at date NOT NULL,
    is_amendment boolean NOT NULL DEFAULT false,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX manager_13f_filings_period_idx
    ON manager_13f_filings (investment_manager_id, report_period DESC, filed_at DESC);

CREATE TABLE manager_13f_positions (
    manager_13f_filing_id uuid NOT NULL
        REFERENCES manager_13f_filings(manager_13f_filing_id) ON DELETE CASCADE,
    cusip text NOT NULL,
    issuer_name text NOT NULL,
    class_title text NOT NULL,
    put_call text NOT NULL DEFAULT '' CHECK (put_call IN ('', 'PUT', 'CALL')),
    ticker text,
    reported_value_usd_thousands numeric NOT NULL
        CHECK (reported_value_usd_thousands >= 0),
    shares_or_principal numeric NOT NULL CHECK (shares_or_principal >= 0),
    share_type text NOT NULL,
    portfolio_weight numeric CHECK (portfolio_weight >= 0 AND portfolio_weight <= 1),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (manager_13f_filing_id, cusip, class_title, put_call)
);

CREATE TABLE krx_index_snapshots (
    krx_index_snapshot_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id text NOT NULL REFERENCES sources(source_id),
    raw_snapshot_id uuid NOT NULL REFERENCES raw_snapshots(raw_snapshot_id),
    index_code text NOT NULL CHECK (index_code IN ('KOSPI_200', 'KOSDAQ_150')),
    effective_date date NOT NULL,
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (index_code, effective_date, raw_snapshot_id)
);

CREATE TABLE krx_index_memberships (
    krx_index_snapshot_id uuid NOT NULL
        REFERENCES krx_index_snapshots(krx_index_snapshot_id) ON DELETE CASCADE,
    asset_id uuid NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    ticker text NOT NULL,
    constituent_name text NOT NULL,
    PRIMARY KEY (krx_index_snapshot_id, asset_id)
);

CREATE INDEX krx_index_memberships_asset_idx
    ON krx_index_memberships (asset_id, krx_index_snapshot_id);

CREATE TABLE analysis_universe_evidence (
    analysis_universe_evidence_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id uuid NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    universe_kind text NOT NULL
        CHECK (universe_kind IN ('core_etf', 'investor_equity', 'krx_index_equity')),
    membership_status text NOT NULL DEFAULT 'active'
        CHECK (membership_status IN ('active', 'cooling', 'archived')),
    evidence_type text NOT NULL
        CHECK (evidence_type IN (
            'etf_catalog', 'sec_13f', 'krx_kospi_200', 'krx_kosdaq_150'
        )),
    evidence_key text NOT NULL,
    source_id text REFERENCES sources(source_id),
    raw_snapshot_id uuid REFERENCES raw_snapshots(raw_snapshot_id),
    exposure_key text REFERENCES etf_exposures(exposure_key),
    effective_from date NOT NULL,
    effective_to date,
    policy_version integer NOT NULL CHECK (policy_version > 0),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (asset_id, universe_kind, evidence_type, evidence_key, effective_from),
    CHECK (effective_to IS NULL OR effective_from <= effective_to),
    CHECK (
        (universe_kind = 'core_etf' AND exposure_key IS NOT NULL)
        OR (universe_kind <> 'core_etf' AND exposure_key IS NULL)
    )
);

CREATE INDEX analysis_universe_evidence_current_idx
    ON analysis_universe_evidence (universe_kind, membership_status, asset_id)
    WHERE effective_to IS NULL;

CREATE TABLE provider_monthly_symbol_usage (
    source_id text NOT NULL REFERENCES sources(source_id),
    usage_month date NOT NULL CHECK (extract(day FROM usage_month) = 1),
    symbol text NOT NULL,
    first_used_at timestamptz NOT NULL,
    last_used_at timestamptz NOT NULL,
    request_count integer NOT NULL DEFAULT 1 CHECK (request_count > 0),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (source_id, usage_month, symbol),
    CHECK (first_used_at <= last_used_at)
);

CREATE INDEX provider_monthly_symbol_usage_count_idx
    ON provider_monthly_symbol_usage (source_id, usage_month);
