-- Adds the announcements widget and a new default layout with a wide clear middle for
-- your reflection. Time, greeting, weather and the day summary stay shallow at the top;
-- the three information cards stay along the bottom.
--
--   +--------+   greeting    +--------+
--   | clock  |    summary    |weather |
--   +--------+---------------+--------+
--   |                                |
--   |              (you)             |
--   |                                |
--   +---------+---------+------------+
--   | calendar|assignments|announcements|
--   +---------+---------+------------+
--
-- On an existing database run it by hand (safe to run twice):
--   docker exec -i sumirrorize-db psql -U sumirrorize < db/init/004_announcements_and_layout.sql
-- Only the defaults change: people who already exist keep their layout and get the new widget.

UPDATE widget SET default_x = v.x, default_y = v.y, default_w = v.w, default_h = v.h
FROM (VALUES
    ('clock',         0.03,  0.03, 0.22, 0.13),
    ('greeting',      0.29,  0.03, 0.42, 0.09),
    ('summary',       0.22,  0.16, 0.56, 0.09),
    ('weather',       0.75,  0.03, 0.22, 0.15),
    ('calendar',      0.03,  0.73, 0.29, 0.24),
    ('assignments',   0.355, 0.73, 0.29, 0.24),
    ('announcements', 0.68,  0.73, 0.29, 0.24)
) AS v(widget_key, x, y, w, h)
WHERE widget.widget_key = v.widget_key;

INSERT INTO widget (widget_key, name, description, default_x, default_y, default_w, default_h)
VALUES ('announcements', 'Announcements', 'Recent announcements from your Brightspace courses.',
        0.68, 0.73, 0.29, 0.24)
ON CONFLICT (widget_key) DO NOTHING;
