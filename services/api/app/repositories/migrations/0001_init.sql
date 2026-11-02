CREATE TABLE IF NOT EXISTS schema_migrations (
  version     INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  checksum    TEXT NOT NULL,
  applied_at  TEXT NOT NULL
);

CREATE TABLE image_asset (
  id               TEXT PRIMARY KEY,
  original_name    TEXT NOT NULL,
  storage_key      TEXT NOT NULL UNIQUE,
  mime_type        TEXT NOT NULL,
  width            INTEGER NOT NULL CHECK (width  > 0),
  height           INTEGER NOT NULL CHECK (height > 0),
  exif_orientation INTEGER NOT NULL DEFAULT 1 CHECK (exif_orientation BETWEEN 1 AND 8),
  bytes            INTEGER NOT NULL CHECK (bytes > 0),
  sha256           TEXT NOT NULL CHECK (length(sha256) = 64),
  created_at       TEXT NOT NULL
);
CREATE INDEX idx_image_asset_created_at ON image_asset(created_at);

CREATE TABLE edit_session (
  id                 TEXT PRIMARY KEY,
  image_id           TEXT NOT NULL REFERENCES image_asset(id) ON DELETE RESTRICT,
  status             TEXT NOT NULL CHECK (status IN ('active','archived')),
  active_revision_id TEXT REFERENCES edit_revision(id) DEFERRABLE INITIALLY DEFERRED,
  head_revision_id   TEXT REFERENCES edit_revision(id) DEFERRABLE INITIALLY DEFERRED,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL
);
CREATE INDEX idx_edit_session_image_id   ON edit_session(image_id);
CREATE INDEX idx_edit_session_created_at ON edit_session(created_at);

CREATE TABLE edit_revision (
  id              TEXT PRIMARY KEY,
  session_id      TEXT NOT NULL REFERENCES edit_session(id) ON DELETE CASCADE,
  parent_id       TEXT REFERENCES edit_revision(id),
  revision_no     INTEGER NOT NULL CHECK (revision_no >= 1),
  recipe_json     TEXT NOT NULL,
  recipe_hash     TEXT NOT NULL,
  source          TEXT NOT NULL CHECK (source IN ('initial','user','ai','reset')),
  idempotency_key TEXT,
  created_at      TEXT NOT NULL,
  UNIQUE (session_id, revision_no),
  UNIQUE (session_id, idempotency_key)
);
CREATE INDEX idx_edit_revision_session_id ON edit_revision(session_id);
CREATE INDEX idx_edit_revision_created_at ON edit_revision(created_at);
