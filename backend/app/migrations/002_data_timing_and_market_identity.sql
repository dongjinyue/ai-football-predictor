ALTER TABLE matches ADD COLUMN half_time_home_score INTEGER;
ALTER TABLE matches ADD COLUMN half_time_away_score INTEGER;

CREATE TABLE market_snapshots_v2 (
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
        time_precision IN ('exact', 'date_only', 'kickoff_bound')
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

-- v1 没有来源和阶段信息。明确标记来源未知，不能把赔率提供方冒充数据来源；
-- 同时仅允许在开球时确认旧快照可用，避免回测使用未知采集时间的信息。
INSERT INTO market_snapshots_v2
SELECT
    old_snapshot.id,
    old_snapshot.match_id,
    old_snapshot.provider,
    'legacy_unknown' AS source,
    old_snapshot.market_type,
    CAST(old_snapshot.handicap AS DECIMAL(8, 2)) AS handicap,
    COALESCE(CAST(old_snapshot.handicap AS VARCHAR), 'none') AS handicap_key,
    old_snapshot.home_value,
    old_snapshot.draw_value,
    old_snapshot.away_value,
    matches.kickoff_at AS captured_at,
    matches.kickoff_at AS available_at,
    'closing' AS stage,
    'kickoff_bound' AS time_precision,
    old_snapshot.created_at
FROM market_snapshots AS old_snapshot
JOIN matches ON matches.id = old_snapshot.match_id
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY
        old_snapshot.match_id,
        old_snapshot.provider,
        old_snapshot.market_type,
        COALESCE(CAST(old_snapshot.handicap AS VARCHAR), 'none')
    ORDER BY old_snapshot.created_at, old_snapshot.id
) = 1;

DROP TABLE market_snapshots;
ALTER TABLE market_snapshots_v2 RENAME TO market_snapshots;

INSERT INTO schema_migrations (version) VALUES (2);
