-- Adds the announcements widget and a new default layout that keeps the middle of the
-- mirror clear for your reflection:
--
--   +-----------+  greeting   +-----------+
--   |  clock    |  summary    |  weather  |
--   +-----------+             |  (tall)   |
--   |           |   (you)     +-----------+
--   | calendar  |             |           |
--   |           +-------------+assignments|
--   |           |announcements|           |
--   |           |             |           |
--   +-----------+-------------+-----------+
--
-- On an existing database run it by hand (safe to run twice):
--   docker exec -i sumirrorize-db psql -U sumirrorize < db/init/004_announcements_and_layout.sql
-- Only the defaults change: people who already exist keep their layout and get the new widget.

UPDATE widget SET default_x = v.x, default_y = v.y, default_w = v.w, default_h = v.h
FROM (VALUES
    ('clock',       0.02, 0.03, 0.28, 0.15),
    ('greeting',    0.32, 0.03, 0.36, 0.10),
    ('summary',     0.32, 0.14, 0.36, 0.12),
    ('weather',     0.70, 0.03, 0.28, 0.30),
    ('calendar',    0.02, 0.21, 0.28, 0.76),
    ('assignments', 0.70, 0.36, 0.28, 0.61),
    ('announcements', 0.32, 0.56, 0.36, 0.41)
) AS v(widget_key, x, y, w, h)
WHERE widget.widget_key = v.widget_key;

INSERT INTO widget (widget_key, name, description, default_x, default_y, default_w, default_h)
VALUES ('announcements', 'Announcements', 'Recent announcements from your Brightspace courses.',
        0.32, 0.56, 0.36, 0.41)
ON CONFLICT (widget_key) DO NOTHING;
