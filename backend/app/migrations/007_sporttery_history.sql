CREATE TABLE sporttery_matches (
    match_id BIGINT PRIMARY KEY,
    core_match_id VARCHAR REFERENCES matches(id),
    match_date DATE NOT NULL,
    match_number VARCHAR NOT NULL,
    match_number_label VARCHAR NOT NULL,
    league_id BIGINT NOT NULL,
    league_name VARCHAR NOT NULL,
    league_abbreviation VARCHAR NOT NULL,
    home_team_id BIGINT NOT NULL,
    home_team_name VARCHAR NOT NULL,
    home_team_full_name VARCHAR NOT NULL,
    away_team_id BIGINT NOT NULL,
    away_team_name VARCHAR NOT NULL,
    away_team_full_name VARCHAR NOT NULL,
    half_time_home_score INTEGER,
    half_time_away_score INTEGER,
    home_score INTEGER,
    away_score INTEGER,
    result VARCHAR CHECK (result IN ('home', 'draw', 'away')),
    handicap DECIMAL(8, 2),
    result_status VARCHAR NOT NULL,
    pool_status VARCHAR NOT NULL,
    raw_sha256 VARCHAR NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (home_team_id <> away_team_id),
    CHECK (home_score IS NULL OR home_score >= 0),
    CHECK (away_score IS NULL OR away_score >= 0)
);

CREATE TABLE sporttery_bonus_snapshots (
    id VARCHAR PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES sporttery_matches(match_id),
    market_type VARCHAR NOT NULL,
    handicap DECIMAL(8, 2),
    handicap_key VARCHAR NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    raw_sha256 VARCHAR NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (match_id, market_type, handicap_key, captured_at)
);

CREATE TABLE sporttery_bonus_outcomes (
    id VARCHAR PRIMARY KEY,
    snapshot_id VARCHAR NOT NULL REFERENCES sporttery_bonus_snapshots(id),
    outcome_code VARCHAR NOT NULL,
    odds_value DOUBLE NOT NULL CHECK (odds_value > 0 AND isfinite(odds_value)),
    UNIQUE (snapshot_id, outcome_code)
);

CREATE TABLE sporttery_single_pools (
    match_id BIGINT NOT NULL REFERENCES sporttery_matches(match_id),
    pool_code VARCHAR NOT NULL,
    is_single BOOLEAN NOT NULL,
    raw_sha256 VARCHAR NOT NULL,
    PRIMARY KEY (match_id, pool_code)
);

CREATE TABLE sporttery_requests (
    request_key VARCHAR PRIMARY KEY,
    request_kind VARCHAR NOT NULL,
    request_url VARCHAR NOT NULL,
    local_path VARCHAR NOT NULL,
    sha256 VARCHAR NOT NULL,
    status_code INTEGER NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO schema_migrations (version) VALUES (7);
