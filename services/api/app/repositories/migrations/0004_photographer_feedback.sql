CREATE TABLE photographer_feedback (
  id                 TEXT PRIMARY KEY,
  image_id           TEXT NOT NULL REFERENCES image_asset(id) ON DELETE CASCADE,
  session_id         TEXT NOT NULL REFERENCES edit_session(id) ON DELETE CASCADE,
  plan_id            TEXT REFERENCES photographer_plan(id) ON DELETE CASCADE,
  revision_id        TEXT REFERENCES edit_revision(id) ON DELETE CASCADE,
  source             TEXT CHECK (source IN ('plan','chat','critique')),
  action             TEXT NOT NULL CHECK (action IN ('accepted','rejected','modified','reset')),
  changed_paths_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(changed_paths_json)),
  rubric_json        TEXT CHECK (rubric_json IS NULL OR json_valid(rubric_json)),
  is_mock            INTEGER NOT NULL CHECK (is_mock IN (0,1)),
  degraded           INTEGER NOT NULL DEFAULT 0 CHECK (degraded IN (0,1)),
  created_at         TEXT NOT NULL,
  UNIQUE (plan_id, action)
);
CREATE INDEX idx_photographer_feedback_image_id ON photographer_feedback(image_id);
CREATE INDEX idx_photographer_feedback_session_id ON photographer_feedback(session_id);
CREATE INDEX idx_photographer_feedback_plan_id ON photographer_feedback(plan_id);
CREATE INDEX idx_photographer_feedback_created_at ON photographer_feedback(created_at);
