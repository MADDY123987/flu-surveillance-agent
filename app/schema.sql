-- Run this once against your CockroachDB cluster to set up the schema.
-- psql "$DATABASE_URL" -f app/schema.sql

-- Time series of raw signal readings (e.g. flu-like illness rate by region/week)
CREATE TABLE IF NOT EXISTS health_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source STRING NOT NULL,           -- e.g. 'cdc_fluview'
    signal_type STRING NOT NULL,      -- e.g. 'flu_like_illness'
    region STRING NOT NULL,           -- e.g. 'California'
    observed_date DATE NOT NULL,
    value FLOAT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, signal_type, region, observed_date)
);

CREATE INDEX IF NOT EXISTS idx_signals_lookup
    ON health_signals (signal_type, region, observed_date DESC);

-- Text reports / advisories, embedded for semantic search over "has this happened before"
CREATE TABLE IF NOT EXISTS health_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source STRING NOT NULL,
    title STRING NOT NULL,
    content STRING NOT NULL,
    region STRING,
    published_date DATE,
    embedding VECTOR(384),             -- matches BAAI/bge-small-en-v1.5 dimension
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Vector index for semantic similarity search
CREATE VECTOR INDEX IF NOT EXISTS idx_reports_embedding
    ON health_reports (embedding);

-- Agent-generated alerts (the "act" output of the reasoning loop)
CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_type STRING NOT NULL,
    region STRING NOT NULL,
    severity STRING NOT NULL,         -- 'info' | 'watch' | 'alert'
    message STRING NOT NULL,
    state STRING NOT NULL DEFAULT 'new',  -- 'new' | 'acknowledged' | 'resolved'
    agent_reasoning JSONB,            -- step-by-step trace, useful for the demo video
    observed_date DATE,               -- date of the underlying data point, distinct from
                                       -- created_at (when this row was written) - can differ
                                       -- significantly for historical/demo agent runs
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Full lifecycle history of each alert's state changes - this is what makes alert
-- handling look like a real operational system rather than a one-shot notification.
CREATE TABLE IF NOT EXISTS alert_state_transitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id UUID NOT NULL REFERENCES alerts(id),
    from_state STRING NOT NULL,
    to_state STRING NOT NULL,
    reason STRING,
    transitioned_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Audit log: every read/write the agent performs against surveillance data
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor STRING NOT NULL,            -- 'ingest_job' | 'agent' | 'api_user'
    action STRING NOT NULL,           -- 'read' | 'write' | 'alert_generated'
    resource STRING NOT NULL,         -- e.g. 'health_signals:California:flu_like_illness'
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
