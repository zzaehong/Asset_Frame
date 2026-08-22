CREATE TABLE krx_backfill_jobs (
    krx_backfill_job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id text NOT NULL REFERENCES sources(source_id),
    as_of_date date NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'completed_with_errors')),
    total_items integer NOT NULL DEFAULT 0 CHECK (total_items >= 0),
    succeeded_items integer NOT NULL DEFAULT 0 CHECK (succeeded_items >= 0),
    no_data_items integer NOT NULL DEFAULT 0 CHECK (no_data_items >= 0),
    failed_items integer NOT NULL DEFAULT 0 CHECK (failed_items >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (start_date <= end_date),
    UNIQUE (source_id, as_of_date, start_date, end_date)
);

CREATE TABLE krx_backfill_items (
    krx_backfill_job_id uuid NOT NULL
        REFERENCES krx_backfill_jobs(krx_backfill_job_id) ON DELETE CASCADE,
    business_date date NOT NULL,
    dataset text NOT NULL
        CHECK (dataset IN ('kospi_prices', 'kosdaq_prices', 'etf_prices')),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'succeeded', 'no_data', 'failed')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    records_accepted integer NOT NULL DEFAULT 0 CHECK (records_accepted >= 0),
    last_error text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (krx_backfill_job_id, business_date, dataset)
);

CREATE INDEX krx_backfill_items_claim_idx
    ON krx_backfill_items (krx_backfill_job_id, status, updated_at, business_date, dataset);
