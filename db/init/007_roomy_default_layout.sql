-- New accounts get a top glance area, a wide unobstructed reflection area, and three
-- equal information cards along the bottom. Existing people keep their chosen layout.
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
