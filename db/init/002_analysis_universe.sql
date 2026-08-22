CREATE TABLE analysis_universe_runs (
    analysis_universe_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    country_code char(2) NOT NULL CHECK (country_code IN ('KR', 'US')),
    as_of_date date NOT NULL,
    lookback_observations integer NOT NULL CHECK (lookback_observations > 0),
    minimum_observations integer NOT NULL CHECK (minimum_observations > 0),
    equity_limit integer NOT NULL CHECK (equity_limit > 0),
    etf_limit integer NOT NULL CHECK (etf_limit > 0),
    input_hash char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (country_code, as_of_date, input_hash)
);

CREATE TABLE analysis_universe_memberships (
    analysis_universe_run_id uuid NOT NULL
        REFERENCES analysis_universe_runs(analysis_universe_run_id) ON DELETE CASCADE,
    asset_id uuid NOT NULL REFERENCES assets(asset_id),
    asset_type asset_type NOT NULL,
    ticker text NOT NULL,
    selected_rank integer NOT NULL CHECK (selected_rank > 0),
    median_dollar_volume numeric,
    observation_count integer NOT NULL CHECK (observation_count >= 0),
    pinned boolean NOT NULL DEFAULT false,
    selection_reason text NOT NULL,
    PRIMARY KEY (analysis_universe_run_id, asset_id),
    UNIQUE (analysis_universe_run_id, asset_type, selected_rank)
);

CREATE INDEX analysis_universe_memberships_asset_idx
    ON analysis_universe_memberships (asset_id, analysis_universe_run_id);
