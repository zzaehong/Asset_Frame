ALTER TABLE financial_facts
    ADD COLUMN fact_key char(64);

CREATE UNIQUE INDEX financial_facts_canonical_key_idx
    ON financial_facts (source_id, asset_id, fact_key)
    WHERE fact_key IS NOT NULL;

CREATE TABLE news_articles (
    news_article_id uuid PRIMARY KEY,
    source_id text NOT NULL REFERENCES sources(source_id),
    raw_snapshot_id uuid NOT NULL REFERENCES raw_snapshots(raw_snapshot_id),
    article_url text NOT NULL,
    title text NOT NULL,
    source_domain text,
    language text,
    source_country text,
    published_at timestamptz NOT NULL,
    fetched_at timestamptz NOT NULL,
    UNIQUE (source_id, article_url)
);

CREATE TABLE news_asset_mentions (
    news_article_id uuid NOT NULL REFERENCES news_articles(news_article_id) ON DELETE CASCADE,
    asset_id uuid NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    matched_query text NOT NULL,
    PRIMARY KEY (news_article_id, asset_id)
);

CREATE INDEX news_articles_published_idx ON news_articles (published_at DESC);
CREATE INDEX news_asset_mentions_asset_idx ON news_asset_mentions (asset_id, news_article_id);
