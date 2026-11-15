-- When enabled, the first person recognized keeps control while other faces enter the frame.
ALTER TABLE person ADD COLUMN IF NOT EXISTS view_lock boolean NOT NULL DEFAULT false;
