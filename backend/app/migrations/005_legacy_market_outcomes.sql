-- Migrate legacy fixed home/draw/away odds into market_outcomes while retaining source evidence.
INSERT INTO market_outcomes (id, snapshot_id, outcome_code, odds_value, source_field)
SELECT 'legacy:' || snapshot.id || ':' || value.outcome_code,
       snapshot.id, value.outcome_code, value.odds_value, value.source_field
FROM market_snapshots AS snapshot,
LATERAL (VALUES
    ('home', snapshot.home_value, 'legacy.home_value'),
    ('draw', snapshot.draw_value, 'legacy.draw_value'),
    ('away', snapshot.away_value, 'legacy.away_value')
) AS value(outcome_code, odds_value, source_field)
WHERE snapshot.market_type IN ('match_result', 'handicap_result', 'asian_handicap')
  AND (snapshot.market_type <> 'asian_handicap' OR value.outcome_code <> 'draw')
  AND value.odds_value > 0 AND isfinite(value.odds_value)
  AND NOT EXISTS (
      SELECT 1 FROM market_outcomes AS existing
      WHERE existing.snapshot_id = snapshot.id AND existing.outcome_code = value.outcome_code
  );

INSERT INTO schema_migrations (version) VALUES (5);
