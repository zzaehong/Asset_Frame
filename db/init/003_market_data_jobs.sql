CREATE TABLE market_data_jobs (
    market_data_job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id text NOT NULL REFERENCES sources(source_id),
    job_type text NOT NULL CHECK (job_type IN ('liquidity_discovery', 'universe_backfill')),
    country_code char(2) NOT NULL CHECK (country_code IN ('KR', 'US')),
    as_of_date date NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'completed_with_errors')),
    total_items integer NOT NULL DEFAULT 0 CHECK (total_items >= 0),
    succeeded_items integer NOT NULL DEFAULT 0 CHECK (succeeded_items >= 0),
    failed_items integer NOT NULL DEFAULT 0 CHECK (failed_items >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (start_date <= end_date),
    UNIQUE (source_id, job_type, country_code, as_of_date, start_date, end_date)
);

CREATE TABLE market_data_job_items (
    market_data_job_id uuid NOT NULL
        REFERENCES market_data_jobs(market_data_job_id) ON DELETE CASCADE,
    ticker text NOT NULL,
    asset_type asset_type NOT NULL,
    exchange_code text,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    records_accepted integer NOT NULL DEFAULT 0 CHECK (records_accepted >= 0),
    last_error text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (market_data_job_id, ticker)
);

CREATE INDEX market_data_job_items_claim_idx
    ON market_data_job_items (market_data_job_id, status, updated_at, ticker);
