CREATE TABLE analysis_task (
  id             TEXT PRIMARY KEY,
  image_id       TEXT NOT NULL REFERENCES image_asset(id) ON DELETE CASCADE,
  image_sha256   TEXT NOT NULL CHECK (length(image_sha256) = 64),
  options_json   TEXT NOT NULL,
  config_key     TEXT NOT NULL,
  dedupe_key     TEXT NOT NULL UNIQUE,
  status         TEXT NOT NULL CHECK (status IN ('pending','processing','completed','failed')),
  stage          TEXT NOT NULL CHECK (stage IN ('queued','preprocessing','vision','features','diagnosis','completed','failed')),
  attempts       INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  error_code     TEXT,
  error_message  TEXT,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL,
  started_at     TEXT,
  completed_at   TEXT
);
CREATE INDEX idx_analysis_task_image_id    ON analysis_task(image_id);
CREATE INDEX idx_analysis_task_status      ON analysis_task(status);
CREATE INDEX idx_analysis_task_created_at  ON analysis_task(created_at);
CREATE INDEX idx_analysis_task_config_key  ON analysis_task(config_key);

CREATE TABLE analysis_result (
  id             TEXT PRIMARY KEY,
  task_id        TEXT NOT NULL UNIQUE REFERENCES analysis_task(id) ON DELETE CASCADE,
  schema_version TEXT NOT NULL,
  is_mock        INTEGER NOT NULL CHECK (is_mock IN (0,1)),
  report_json    TEXT NOT NULL,
  created_at     TEXT NOT NULL
);
CREATE INDEX idx_analysis_result_task_id ON analysis_result(task_id);