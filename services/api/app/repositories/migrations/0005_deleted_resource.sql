-- Deletion is a hard delete; this table only remembers that an id was already
-- removed so a repeated DELETE can stay idempotent (204) instead of reporting
-- 404 for a resource the caller just deleted. It stores no content.
CREATE TABLE deleted_resource (
  kind       TEXT NOT NULL CHECK (kind IN ('image', 'session')),
  id         TEXT NOT NULL,
  deleted_at TEXT NOT NULL,
  PRIMARY KEY (kind, id)
);
