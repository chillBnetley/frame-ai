ALTER TABLE photographer_plan ADD COLUMN base_revision_id TEXT;

ALTER TABLE edit_revision ADD COLUMN plan_id TEXT;
ALTER TABLE edit_revision ADD COLUMN style_id TEXT;
ALTER TABLE edit_revision ADD COLUMN style_version TEXT;
ALTER TABLE edit_revision ADD COLUMN conversion_mode TEXT
  CHECK (conversion_mode IS NULL OR conversion_mode IN ('natural','style','creative'));
ALTER TABLE edit_revision ADD COLUMN style_strength REAL
  CHECK (style_strength IS NULL OR (style_strength >= 0 AND style_strength <= 1));
ALTER TABLE edit_revision ADD COLUMN render_key TEXT;

CREATE INDEX idx_edit_revision_plan_id ON edit_revision(plan_id);
CREATE INDEX idx_photographer_plan_base_revision_id ON photographer_plan(base_revision_id);
