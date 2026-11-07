CREATE TABLE photographer_plan (
  id             TEXT PRIMARY KEY,
  image_id       TEXT NOT NULL REFERENCES image_asset(id) ON DELETE CASCADE,
  session_id     TEXT NOT NULL REFERENCES edit_session(id) ON DELETE CASCADE,
  analysis_id    TEXT NOT NULL REFERENCES analysis_task(id) ON DELETE CASCADE,
  mode           TEXT NOT NULL CHECK (mode IN ('auto','style','chat')),
  style_id       TEXT,
  style_version  TEXT,
  style_strength REAL CHECK (style_strength IS NULL OR (style_strength >= 0 AND style_strength <= 1)),
  provider       TEXT NOT NULL,
  model          TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  is_mock        INTEGER NOT NULL CHECK (is_mock IN (0,1)),
  degraded       INTEGER NOT NULL DEFAULT 0 CHECK (degraded IN (0,1)),
  confidence     REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  plan_json      TEXT NOT NULL,
  recipe_json    TEXT NOT NULL,
  recipe_hash    TEXT NOT NULL,
  created_at     TEXT NOT NULL
);
CREATE INDEX idx_photographer_plan_image_id   ON photographer_plan(image_id);
CREATE INDEX idx_photographer_plan_session_id ON photographer_plan(session_id);
CREATE INDEX idx_photographer_plan_analysis_id ON photographer_plan(analysis_id);
CREATE INDEX idx_photographer_plan_created_at ON photographer_plan(created_at);
