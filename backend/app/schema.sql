CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS competitions (
    id VARCHAR PRIMARY KEY,
    name_zh VARCHAR NOT NULL,
    name_en VARCHAR,
    country_code VARCHAR,
    source VARCHAR NOT NULL,
    source_competition_id VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source, source_competition_id)
);

CREATE TABLE IF NOT EXISTS teams (
    id VARCHAR PRIMARY KEY,
    name_zh VARCHAR NOT NULL,
    name_en VARCHAR,
    country_code VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS team_aliases (
    id VARCHAR PRIMARY KEY,
    team_id VARCHAR NOT NULL REFERENCES teams(id),
    source VARCHAR NOT NULL,
    alias VARCHAR NOT NULL,
    normalized_alias VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source, normalized_alias)
);

CREATE TABLE IF NOT EXISTS matches (
    id VARCHAR PRIMARY KEY,
    competition_id VARCHAR NOT NULL REFERENCES competitions(id),
    season VARCHAR NOT NULL,
    kickoff_at TIMESTAMPTZ NOT NULL,
    home_team_id VARCHAR NOT NULL REFERENCES teams(id),
    away_team_id VARCHAR NOT NULL REFERENCES teams(id),
    home_score INTEGER,
    away_score INTEGER,
    status VARCHAR NOT NULL CHECK (status IN ('scheduled', 'finished', 'postponed', 'cancelled')),
    source VARCHAR NOT NULL,
    source_match_id VARCHAR NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (home_team_id <> away_team_id),
    CHECK (home_score IS NULL OR home_score >= 0),
    CHECK (away_score IS NULL OR away_score >= 0),
    UNIQUE (source, source_match_id)
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id VARCHAR PRIMARY KEY,
    match_id VARCHAR NOT NULL REFERENCES matches(id),
    provider VARCHAR NOT NULL,
    market_type VARCHAR NOT NULL,
    handicap INTEGER,
    home_value DOUBLE,
    draw_value DOUBLE,
    away_value DOUBLE,
    captured_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (home_value IS NULL OR home_value > 0),
    CHECK (draw_value IS NULL OR draw_value > 0),
    CHECK (away_value IS NULL OR away_value > 0),
    UNIQUE (match_id, provider, market_type, handicap, captured_at)
);

INSERT OR IGNORE INTO schema_migrations (version) VALUES (1);
