-- V6.3 Batch 8: a task may consume the base asset graded flat instead of its
-- raw pixels. Existing rows stay on 'base', so every pre-Batch-8 task keeps the
-- exact input it was created with. The input sha and recipe hash record which
-- pixels the protected-region write-back was verified against.

ALTER TABLE generative_task ADD COLUMN base_mode TEXT NOT NULL DEFAULT 'base'
  CHECK (base_mode IN ('base', 'graded'));
ALTER TABLE generative_task ADD COLUMN input_sha256 TEXT;
ALTER TABLE generative_task ADD COLUMN input_recipe_hash TEXT;