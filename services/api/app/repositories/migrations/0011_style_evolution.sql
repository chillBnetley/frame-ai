-- V6.2 Visual DNA: style evolution proposals.
-- Feedback rows already live in personal_style_feedback (migration 0010); this
-- table records the candidate produced from confirmed personal-style feedback
-- and whether the user actively applied it. A proposal never mutates the style
-- until an explicit apply, so user-confirmed profiles are never changed silently.

CREATE TABLE personal_style_evolution (
  id              TEXT PRIMARY KEY,
  style_id        TEXT NOT NULL REFERENCES personal_style(id) ON DELETE CASCADE,
  base_version    TEXT NOT NULL,
  new_version     TEXT,
  feedback_ids_json TEXT NOT NULL,
  reason          TEXT NOT NULL,
  summary         TEXT NOT NULL,
  candidate_json  TEXT NOT NULL,
  definition_json TEXT NOT NULL,
  status          TEXT NOT NULL CHECK (status IN ('proposed','confirmed','discarded')),
  created_at      TEXT NOT NULL,
  confirmed_at    TEXT
);
CREATE INDEX idx_personal_evolution_style
  ON personal_style_evolution(style_id, created_at);
CREATE INDEX idx_personal_evolution_status
  ON personal_style_evolution(style_id, status);