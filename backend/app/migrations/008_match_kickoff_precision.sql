-- 体彩旧列表只有比赛日期。核心表保留排序锚点，同时用精度字段禁止把它冒充精确开球时间。
ALTER TABLE matches
ADD COLUMN kickoff_time_precision VARCHAR DEFAULT 'exact';

INSERT INTO schema_migrations (version) VALUES (8);
