CREATE TABLE IF NOT EXISTS market_outcomes (
    id VARCHAR PRIMARY KEY,
    snapshot_id VARCHAR NOT NULL REFERENCES market_snapshots(id),
    outcome_code VARCHAR NOT NULL,
    odds_value DOUBLE NOT NULL CHECK (odds_value > 0),
    normalized_probability DOUBLE CHECK (
        normalized_probability IS NULL OR
        (normalized_probability >= 0 AND normalized_probability <= 1)
    ),
    source_field VARCHAR NOT NULL,
    UNIQUE (snapshot_id, outcome_code)
);

CREATE TABLE IF NOT EXISTS import_runs (
    id VARCHAR PRIMARY KEY,
    source VARCHAR NOT NULL,
    status VARCHAR NOT NULL CHECK (
        status IN ('running', 'completed', 'completed_with_errors', 'failed')
    ),
    requested_files INTEGER NOT NULL CHECK (requested_files >= 0),
    completed_files INTEGER NOT NULL DEFAULT 0 CHECK (completed_files >= 0),
    failed_files INTEGER NOT NULL DEFAULT 0 CHECK (failed_files >= 0),
    imported_matches INTEGER NOT NULL DEFAULT 0 CHECK (imported_matches >= 0),
    skipped_rows INTEGER NOT NULL DEFAULT 0 CHECK (skipped_rows >= 0),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    error_summary VARCHAR
);

CREATE TABLE IF NOT EXISTS import_files (
    id VARCHAR PRIMARY KEY,
    run_id VARCHAR NOT NULL REFERENCES import_runs(id),
    source VARCHAR NOT NULL,
    competition_code VARCHAR NOT NULL,
    season VARCHAR NOT NULL,
    source_url VARCHAR NOT NULL,
    local_path VARCHAR,
    sha256 VARCHAR,
    status VARCHAR NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    imported_matches INTEGER NOT NULL DEFAULT 0,
    skipped_rows INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR,
    UNIQUE (run_id, source_url)
);

INSERT INTO schema_migrations (version) VALUES (3);
