ALTER TABLE photographer_plan ADD COLUMN conversion_mode TEXT
  CHECK (conversion_mode IS NULL OR conversion_mode IN ('natural','style','creative'));

CREATE INDEX idx_photographer_plan_conversion_mode ON photographer_plan(conversion_mode);
