-- 下载时刻属于原始文件审计，不是市场赔率的采集或可用时间。
ALTER TABLE import_files
ADD COLUMN IF NOT EXISTS downloaded_at TIMESTAMPTZ;

INSERT INTO schema_migrations (version)
SELECT 4
WHERE NOT EXISTS (
    SELECT 1 FROM schema_migrations WHERE version = 4
);
