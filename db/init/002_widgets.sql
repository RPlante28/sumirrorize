-- The widgets the mirror ships with and where they sit by default. Positions are
-- fractions of the screen: (0, 0) is the top-left corner, (1, 1) the bottom-right.
INSERT INTO widget (widget_key, name, description, default_x, default_y, default_w, default_h) VALUES
    ('clock',       'Clock',       'Current time and date.',                                0.03, 0.03, 0.25, 0.12),
    ('weather',     'Weather',     'Current conditions and today''s forecast.',             0.72, 0.03, 0.25, 0.15),
    ('summary',     'Day summary', 'A short summary of what the day holds.',                0.20, 0.22, 0.60, 0.15),
    ('greeting',    'Greeting',    'Greets the person by name when the mirror sees them.',  0.20, 0.40, 0.60, 0.10),
    ('calendar',    'Calendar',    'Today''s classes and events from Brightspace.',          0.03, 0.62, 0.45, 0.35),
    ('assignments', 'Assignments', 'Upcoming and overdue assignments from Brightspace.',     0.52, 0.62, 0.45, 0.35);
