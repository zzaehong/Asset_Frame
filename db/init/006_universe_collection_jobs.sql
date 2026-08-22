CREATE TABLE universe_collection_jobs (
    universe_collection_job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id text NOT NULL REFERENCES sources(source_id),
    job_type text NOT NULL
        CHECK (job_type IN ('sec_fundamentals', 'opendart_fundamentals', 'gdelt_news')),
    country_code char(2) NOT NULL CHECK (country_code IN ('KR', 'US')),
    as_of_date date NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    max_news_records integer NOT NULL DEFAULT 75
        CHECK (max_news_records BETWEEN 1 AND 250),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'completed_with_errors')),
    total_items integer NOT NULL DEFAULT 0 CHECK (total_items >= 0),
    succeeded_items integer NOT NULL DEFAULT 0 CHECK (succeeded_items >= 0),
    no_data_items integer NOT NULL DEFAULT 0 CHECK (no_data_items >= 0),
    failed_items integer NOT NULL DEFAULT 0 CHECK (failed_items >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (start_date <= end_date),
    UNIQUE (
        source_id, job_type, country_code, as_of_date, start_date, end_date, max_news_records
    )
);

CREATE TABLE universe_collection_items (
    universe_collection_job_id uuid NOT NULL
        REFERENCES universe_collection_jobs(universe_collection_job_id) ON DELETE CASCADE,
    asset_id uuid NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    ticker text NOT NULL,
    external_identifier text,
    search_query text,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'succeeded', 'no_data', 'failed')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    records_accepted integer NOT NULL DEFAULT 0 CHECK (records_accepted >= 0),
    last_error text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (universe_collection_job_id, asset_id)
);

CREATE INDEX universe_collection_items_claim_idx
    ON universe_collection_items (
        universe_collection_job_id, status, updated_at, ticker, asset_id
    );
