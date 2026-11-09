CREATE TABLE style_profile (
  id              TEXT PRIMARY KEY,
  kind            TEXT NOT NULL CHECK (kind IN ('master','genre')),
  name            TEXT NOT NULL,
  current_version TEXT NOT NULL,
  enabled         INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
CREATE INDEX idx_style_profile_kind ON style_profile(kind);
CREATE INDEX idx_style_profile_enabled ON style_profile(enabled);

CREATE TABLE style_profile_version (
  style_id     TEXT NOT NULL REFERENCES style_profile(id) ON DELETE CASCADE,
  version      TEXT NOT NULL,
  profile_json TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  PRIMARY KEY (style_id, version)
);

CREATE TABLE style_favorite (
  style_id   TEXT PRIMARY KEY REFERENCES style_profile(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL
);