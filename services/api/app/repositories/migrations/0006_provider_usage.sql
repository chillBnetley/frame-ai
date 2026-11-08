-- Daily provider usage counters (L14). One row per UTC date and provider kind.
-- Only counts are stored: no prompt, response, image or key content ever lands here.
CREATE TABLE provider_usage (
  date TEXT NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('vision', 'decision', 'planner')),
  requests INTEGER NOT NULL DEFAULT 0 CHECK (requests >= 0),
  tokens_estimated INTEGER NOT NULL DEFAULT 0 CHECK (tokens_estimated >= 0),
  tokens_reported INTEGER NOT NULL DEFAULT 0 CHECK (tokens_reported >= 0),
  updated_at TEXT NOT NULL,
  PRIMARY KEY (date, provider)
);
