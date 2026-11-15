-- Sumirrorize schema. Postgres runs the files in db/init/ in name order, but only when the data
-- volume is empty (db/README.md says how to change an existing database).

CREATE EXTENSION IF NOT EXISTS vector;

-- keeps updated_at right without every caller having to remember
CREATE FUNCTION touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- a fraction of the screen, so a layout looks the same on any screen size
CREATE DOMAIN screen_fraction AS real CHECK (VALUE BETWEEN 0 AND 1);


-- One row per person, created the first time they sign in to the app (005_google_accounts.sql).
CREATE TABLE person (
    person_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    display_name text NOT NULL CHECK (btrim(display_name) <> ''),
    -- SHA-256 of their API key. The key itself is shown once and never stored.
    api_key_hash bytea NOT NULL UNIQUE CHECK (octet_length(api_key_hash) = 32),
    created_at   timestamptz NOT NULL DEFAULT now()
);


-- A person's face pictures. A new upload replaces the whole set.
CREATE TABLE picture (
    pic_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    person_id  bigint NOT NULL REFERENCES person ON DELETE CASCADE,
    -- which shot this is: 'front', 'left', ... Plain text, so new angles need no schema change.
    angle      text NOT NULL CHECK (angle ~ '^[a-z][a-z0-9_]*$'),
    image      bytea NOT NULL CHECK (octet_length(image) BETWEEN 1 AND 10 * 1024 * 1024),
    mime_type  text NOT NULL CHECK (mime_type IN ('image/jpeg', 'image/png', 'image/webp')),
    -- 128-number face fingerprint from OpenCV's SFace model
    face_encoding vector(128),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX picture_person_id ON picture (person_id);


-- The widgets the mirror can show, same for everyone (002_widgets.sql has the list).
CREATE TABLE widget (
    widget_key       text PRIMARY KEY CHECK (widget_key ~ '^[a-z][a-z0-9_]*$'),
    name             text NOT NULL,
    description      text NOT NULL,
    -- what a new person starts with
    default_enabled  boolean NOT NULL DEFAULT true,
    default_x        screen_fraction NOT NULL,
    default_y        screen_fraction NOT NULL,
    default_w        screen_fraction NOT NULL CHECK (default_w > 0),
    default_h        screen_fraction NOT NULL CHECK (default_h > 0),
    default_settings jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(default_settings) = 'object'),
    CHECK (default_x + default_w <= 1 AND default_y + default_h <= 1)
);


-- How one person has one widget set up. Everyone has a row for every widget, so reading a
-- layout never has to fill in gaps.
CREATE TABLE person_widget (
    person_id  bigint NOT NULL REFERENCES person ON DELETE CASCADE,
    widget_key text NOT NULL REFERENCES widget ON UPDATE CASCADE ON DELETE CASCADE,
    enabled    boolean NOT NULL,
    -- top-left corner (x, y) and size (w, h), as screen fractions
    x          screen_fraction NOT NULL,
    y          screen_fraction NOT NULL,
    w          screen_fraction NOT NULL CHECK (w > 0),
    h          screen_fraction NOT NULL CHECK (h > 0),
    -- per-widget options, e.g. {"units": "metric"} for weather
    settings   jsonb NOT NULL CHECK (jsonb_typeof(settings) = 'object'),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (person_id, widget_key),
    CHECK (x + w <= 1 AND y + h <= 1)
);

CREATE TRIGGER person_widget_touch BEFORE UPDATE ON person_widget
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- a new person gets every widget at its default layout
CREATE FUNCTION give_new_person_widgets() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO person_widget (person_id, widget_key, enabled, x, y, w, h, settings)
    SELECT NEW.person_id, widget_key, default_enabled,
           default_x, default_y, default_w, default_h, default_settings
    FROM widget;
    RETURN NULL;
END;
$$;

CREATE TRIGGER person_gets_widgets AFTER INSERT ON person
    FOR EACH ROW EXECUTE FUNCTION give_new_person_widgets();

-- a newly added widget is given to everyone who already exists
CREATE FUNCTION give_everyone_new_widget() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO person_widget (person_id, widget_key, enabled, x, y, w, h, settings)
    SELECT person_id, NEW.widget_key, NEW.default_enabled,
           NEW.default_x, NEW.default_y, NEW.default_w, NEW.default_h, NEW.default_settings
    FROM person;
    RETURN NULL;
END;
$$;

CREATE TRIGGER widget_given_to_everyone AFTER INSERT ON widget
    FOR EACH ROW EXECUTE FUNCTION give_everyone_new_widget();
