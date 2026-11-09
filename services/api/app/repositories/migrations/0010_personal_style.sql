-- V6.2 Visual DNA: personal style aggregate.
-- Personal styles are stored separately from the master/genre archive so the
-- public style library and its favourite/recommendation semantics stay intact.

CREATE TABLE personal_style (
  id              TEXT PRIMARY KEY,
  owner_id        TEXT NOT NULL,
  name            TEXT NOT NULL,
  description     TEXT NOT NULL,
  source          TEXT NOT NULL CHECK (source IN ('photos','custom','mixed','evolution')),
  status          TEXT NOT NULL CHECK (status IN ('draft','published','disabled')),
  favorite        INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0,1)),
  current_version TEXT NOT NULL,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  deleted_at      TEXT
);
CREATE INDEX idx_personal_style_owner_status ON personal_style(owner_id, status);
CREATE UNIQUE INDEX idx_personal_style_owner_name
  ON personal_style(owner_id, name) WHERE deleted_at IS NULL;

CREATE TABLE personal_style_version (
  style_id        TEXT NOT NULL REFERENCES personal_style(id) ON DELETE CASCADE,
  version         TEXT NOT NULL,
  profile_json    TEXT NOT NULL,
  definition_json TEXT NOT NULL,
  change_source   TEXT NOT NULL
                  CHECK (change_source IN ('analysis','user','custom','mix','evolution','restore')),
  change_note     TEXT,
  created_at      TEXT NOT NULL,
  PRIMARY KEY (style_id, version)
);
CREATE INDEX idx_personal_style_version_created
  ON personal_style_version(style_id, created_at);

CREATE TABLE personal_style_reference (
  id            TEXT PRIMARY KEY,
  style_id      TEXT NOT NULL REFERENCES personal_style(id) ON DELETE CASCADE,
  image_id      TEXT REFERENCES image_asset(id) ON DELETE SET NULL,
  image_sha256  TEXT NOT NULL CHECK (length(image_sha256) = 64),
  analysis_id   TEXT,
  original_name TEXT NOT NULL,
  consent_scope TEXT NOT NULL CHECK (consent_scope IN ('analysis_only')),
  consent_at    TEXT NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('active','removed','missing')),
  added_at      TEXT NOT NULL,
  removed_at    TEXT,
  UNIQUE (style_id, image_id)
);
CREATE INDEX idx_personal_reference_style ON personal_style_reference(style_id, status);
CREATE INDEX idx_personal_reference_image ON personal_style_reference(image_id);

CREATE TABLE personal_style_photo_feature (
  reference_id      TEXT PRIMARY KEY REFERENCES personal_style_reference(id) ON DELETE CASCADE,
  style_id          TEXT NOT NULL REFERENCES personal_style(id) ON DELETE CASCADE,
  image_sha256      TEXT NOT NULL CHECK (length(image_sha256) = 64),
  analysis_id       TEXT NOT NULL,
  extractor_version TEXT NOT NULL,
  features_json     TEXT NOT NULL,
  confidence        REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  is_mock           INTEGER NOT NULL CHECK (is_mock IN (0,1)),
  created_at        TEXT NOT NULL
);
CREATE INDEX idx_personal_feature_style ON personal_style_photo_feature(style_id);

CREATE TABLE personal_style_feedback (
  id              TEXT PRIMARY KEY,
  style_id        TEXT NOT NULL REFERENCES personal_style(id) ON DELETE CASCADE,
  style_version   TEXT NOT NULL,
  feedback_type   TEXT NOT NULL,
  note            TEXT,
  scope           TEXT NOT NULL CHECK (scope IN ('single_edit','profile')),
  applied_version TEXT,
  created_at      TEXT NOT NULL
);
CREATE INDEX idx_personal_feedback_style
  ON personal_style_feedback(style_id, created_at);

-- Repeated deletes stay idempotent after the aggregate rows are gone.
CREATE TABLE personal_style_tombstone (
  style_id   TEXT PRIMARY KEY,
  owner_id   TEXT NOT NULL,
  deleted_at TEXT NOT NULL
);
