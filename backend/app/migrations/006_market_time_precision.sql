-- Allow every time precision value produced by the parser while preserving existing data.
CREATE TABLE market_outcomes_v6_backup (
    id VARCHAR PRIMARY KEY,
    snapshot_id VARCHAR NOT NULL,
    outcome_code VARCHAR NOT NULL,
    odds_value DOUBLE NOT NULL,
    normalized_probability DOUBLE,
    source_field VARCHAR NOT NULL
);

INSERT INTO market_outcomes_v6_backup
SELECT id, snapshot_id, outcome_code, odds_value, normalized_probability, source_field
FROM market_outcomes;

DROP TABLE market_outcomes;

CREATE TABLE market_snapshots_v6 (
    id VARCHAR PRIMARY KEY,
    match_id VARCHAR NOT NULL REFERENCES matches(id),
    provider VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    market_type VARCHAR NOT NULL,
    handicap DECIMAL(8, 2),
    handicap_key VARCHAR NOT NULL,
    home_value DOUBLE,
    draw_value DOUBLE,
    away_value DOUBLE,
    captured_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    stage VARCHAR NOT NULL CHECK (stage IN ('pre_match', 'closing')),
    time_precision VARCHAR NOT NULL CHECK (
        time_precision IN (
            'exact',
            'date_only',
            'kickoff_bound',
            'date_only_unknown',
            'result_after_kickoff'
        )
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (handicap_key = COALESCE(CAST(handicap AS VARCHAR), 'none')),
    CHECK (home_value IS NULL OR home_value > 0),
    CHECK (draw_value IS NULL OR draw_value > 0),
    CHECK (away_value IS NULL OR away_value > 0),
    CHECK (captured_at <= available_at),
    UNIQUE (
        match_id,
        provider,
        source,
        market_type,
        handicap_key,
        captured_at,
        stage
    )
);

INSERT INTO market_snapshots_v6
SELECT
    id,
    match_id,
    provider,
    source,
    market_type,
    handicap,
    handicap_key,
    home_value,
    draw_value,
    away_value,
    captured_at,
    available_at,
    stage,
    time_precision,
    created_at
FROM market_snapshots;

DROP TABLE market_snapshots;
ALTER TABLE market_snapshots_v6 RENAME TO market_snapshots;

CREATE TABLE market_outcomes (
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

INSERT INTO market_outcomes
SELECT id, snapshot_id, outcome_code, odds_value, normalized_probability, source_field
FROM market_outcomes_v6_backup;

DROP TABLE market_outcomes_v6_backup;

INSERT INTO schema_migrations (version) VALUES (6);
