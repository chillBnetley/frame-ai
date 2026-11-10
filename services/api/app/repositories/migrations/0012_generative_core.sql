-- V6.3 Generative Core: immutable generated pixels, raster masks, tasks,
-- candidate results, and the revision link that makes a generated asset the
-- new render base. All generative rows stay separate from image_asset so the
-- user's uploaded library and its deletion semantics are unchanged.

CREATE TABLE generated_asset (
  id           TEXT PRIMARY KEY,
  image_id     TEXT NOT NULL REFERENCES image_asset(id) ON DELETE CASCADE,
  task_id      TEXT,
  result_id    TEXT,
  kind         TEXT NOT NULL CHECK (kind IN ('generative')),
  storage_key  TEXT NOT NULL UNIQUE,
  sha256       TEXT NOT NULL CHECK (length(sha256) = 64),
  width        INTEGER NOT NULL CHECK (width > 0),
  height       INTEGER NOT NULL CHECK (height > 0),
  bytes        INTEGER NOT NULL CHECK (bytes > 0),
  mime_type    TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  deleted_at   TEXT
);
CREATE INDEX idx_generated_asset_image ON generated_asset(image_id);
CREATE UNIQUE INDEX idx_generated_asset_result
  ON generated_asset(result_id) WHERE result_id IS NOT NULL;

CREATE TABLE generative_mask (
  id                     TEXT PRIMARY KEY,
  owner_id               TEXT NOT NULL,
  image_id               TEXT NOT NULL REFERENCES image_asset(id) ON DELETE CASCADE,
  base_generated_asset_id TEXT REFERENCES generated_asset(id) ON DELETE CASCADE,
  kind                   TEXT NOT NULL
                         CHECK (kind IN ('brush', 'rect', 'ellipse', 'semantic', 'ai_proposal')),
  source                 TEXT NOT NULL CHECK (source IN ('user', 'semantic', 'ai')),
  coordinate_space       TEXT NOT NULL CHECK (coordinate_space IN ('base-normalized')),
  width                  INTEGER NOT NULL CHECK (width > 0),
  height                 INTEGER NOT NULL CHECK (height > 0),
  storage_key            TEXT NOT NULL UNIQUE,
  sha256                 TEXT NOT NULL CHECK (length(sha256) = 64),
  feather                REAL NOT NULL DEFAULT 0
                         CHECK (feather >= 0 AND feather <= 100),
  inverted               INTEGER NOT NULL DEFAULT 0 CHECK (inverted IN (0, 1)),
  strokes_json           TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(strokes_json)),
  created_at             TEXT NOT NULL,
  deleted_at             TEXT
);
CREATE INDEX idx_generative_mask_image ON generative_mask(image_id);
CREATE INDEX idx_generative_mask_base ON generative_mask(base_generated_asset_id);

CREATE TABLE generative_task (
  id                       TEXT PRIMARY KEY,
  owner_id                 TEXT NOT NULL,
  image_id                 TEXT NOT NULL REFERENCES image_asset(id) ON DELETE CASCADE,
  session_id               TEXT NOT NULL REFERENCES edit_session(id) ON DELETE CASCADE,
  base_revision_id         TEXT REFERENCES edit_revision(id) ON DELETE SET NULL,
  base_generated_asset_id  TEXT REFERENCES generated_asset(id) ON DELETE SET NULL,
  task_type                TEXT NOT NULL
                           CHECK (task_type IN ('outpaint', 'inpaint', 'remove', 'local_edit')),
  instruction              TEXT NOT NULL DEFAULT '',
  plan_json                TEXT NOT NULL CHECK (json_valid(plan_json)),
  params_json              TEXT NOT NULL CHECK (json_valid(params_json)),
  mask_id                  TEXT REFERENCES generative_mask(id) ON DELETE RESTRICT,
  provider                 TEXT NOT NULL,
  model                    TEXT NOT NULL,
  prompt_version           TEXT NOT NULL,
  provider_job_id          TEXT,
  is_mock                  INTEGER NOT NULL CHECK (is_mock IN (0, 1)),
  status                   TEXT NOT NULL
                           CHECK (status IN ('created', 'validating', 'queued', 'processing',
                                             'succeeded', 'failed', 'cancelled', 'expired')),
  stage                    TEXT NOT NULL
                           CHECK (stage IN ('queued', 'preparing_input', 'submitting',
                                            'generating', 'validating', 'saving',
                                            'completed', 'failed')),
  attempts                 INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  max_attempts             INTEGER NOT NULL DEFAULT 2 CHECK (max_attempts >= 1),
  cancel_requested         INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
  consent_at               TEXT,
  provider_retention       TEXT NOT NULL DEFAULT '',
  error_code               TEXT,
  error_message            TEXT,
  dedupe_key               TEXT NOT NULL UNIQUE,
  idempotency_key          TEXT,
  created_at               TEXT NOT NULL,
  updated_at               TEXT NOT NULL,
  started_at               TEXT,
  completed_at             TEXT,
  expires_at               TEXT NOT NULL,
  UNIQUE (owner_id, idempotency_key)
);
CREATE INDEX idx_generative_task_image ON generative_task(image_id);
CREATE INDEX idx_generative_task_session ON generative_task(session_id);
CREATE INDEX idx_generative_task_status ON generative_task(status);
CREATE INDEX idx_generative_task_created ON generative_task(created_at);

CREATE TABLE generative_result (
  id              TEXT PRIMARY KEY,
  task_id         TEXT NOT NULL REFERENCES generative_task(id) ON DELETE CASCADE,
  result_index    INTEGER NOT NULL CHECK (result_index >= 0),
  storage_key     TEXT NOT NULL UNIQUE,
  sha256          TEXT NOT NULL CHECK (length(sha256) = 64),
  width           INTEGER NOT NULL CHECK (width > 0),
  height          INTEGER NOT NULL CHECK (height > 0),
  bytes           INTEGER NOT NULL CHECK (bytes > 0),
  mime_type       TEXT NOT NULL,
  status          TEXT NOT NULL
                  CHECK (status IN ('candidate', 'accepted', 'rejected', 'discarded')),
  validation_json TEXT NOT NULL CHECK (json_valid(validation_json)),
  revision_id     TEXT,
  created_at      TEXT NOT NULL,
  decided_at      TEXT,
  UNIQUE (task_id, result_index)
);
CREATE INDEX idx_generative_result_task ON generative_result(task_id);
CREATE INDEX idx_generative_result_status ON generative_result(status);

-- A revision may render from a generated asset instead of the uploaded
-- original. NULL keeps every pre-V6.3 revision on the original byte-for-byte.
ALTER TABLE edit_revision ADD COLUMN base_generated_asset_id TEXT
  REFERENCES generated_asset(id) ON DELETE SET NULL;
ALTER TABLE edit_revision ADD COLUMN generative_task_id TEXT
  REFERENCES generative_task(id) ON DELETE SET NULL;

CREATE INDEX idx_edit_revision_base_asset
  ON edit_revision(base_generated_asset_id);
CREATE INDEX idx_edit_revision_generative_task
  ON edit_revision(generative_task_id);
