CREATE TABLE sporttery_preview_sources (
    match_id BIGINT NOT NULL REFERENCES sporttery_matches(match_id),
    dataset VARCHAR NOT NULL,
    status VARCHAR NOT NULL CHECK (status IN ('completed', 'empty')),
    request_url VARCHAR NOT NULL,
    local_path VARCHAR NOT NULL,
    sha256 VARCHAR NOT NULL,
    status_code INTEGER NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (match_id, dataset)
);

INSERT INTO schema_migrations (version) VALUES (9);
