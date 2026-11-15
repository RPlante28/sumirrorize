-- Sumirrorize schema. Postgres runs every file in db/init/ in name order, but only
-- when the data volume is empty (see db/README.md for how to apply changes).

CREATE EXTENSION IF NOT EXISTS vector;

-- Keeps updated_at honest without every caller having to remember it.
CREATE FUNCTION touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- A fraction of the screen, so a layout looks the same on any screen size.
CREATE DOMAIN screen_fraction AS real CHECK (VALUE BETWEEN 0 AND 1);


-- One row per person. Created the first time they sign in to the app (see 005_google_accounts.sql).
CREATE TABLE person (
    person_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    display_name text NOT NULL CHECK (btrim(display_name) <> ''),
    -- SHA-256 of the person's API key. The key itself is shown to them once and never
    -- stored, so a leaked database can't be used to read anyone's data.
    api_key_hash bytea NOT NULL UNIQUE CHECK (octet_length(api_key_hash) = 32),
    created_at   timestamptz NOT NULL DEFAULT now()
);


-- A person's set of pictures, any number of them. Uploading a new set replaces the whole
-- old set (delete + insert in one transaction; see db/README.md).
CREATE TABLE picture (
    pic_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    person_id  bigint NOT NULL REFERENCES person ON DELETE CASCADE,
    -- Which shot this is, e.g. 'front', 'left', 'right'. Plain text so adding new
    -- angles needs no schema change.
    angle      text NOT NULL CHECK (angle ~ '^[a-z][a-z0-9_]*$'),
    image      bytea NOT NULL CHECK (octet_length(image) BETWEEN 1 AND 10 * 1024 * 1024),
    mime_type  text NOT NULL CHECK (mime_type IN ('image/jpeg', 'image/png', 'image/webp')),
    -- The 128-number face fingerprint from the face_recognition library. NULL when no
    -- face was found, which is common for side-on shots.
    face_encoding vector(128),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX picture_person_id ON picture (person_id);


-- The widgets the mirror can show. Same for everyone; see 002_widgets.sql for the list.
CREATE TABLE widget (
    widget_key       text PRIMARY KEY CHECK (widget_key ~ '^[a-z][a-z0-9_]*$'),
    name             text NOT NULL,
    description      text NOT NULL,
    -- What a new person starts with.
    default_enabled  boolean NOT NULL DEFAULT true,
    default_x        screen_fraction NOT NULL,
    default_y        screen_fraction NOT NULL,
    default_w        screen_fraction NOT NULL CHECK (default_w > 0),
    default_h        screen_fraction NOT NULL CHECK (default_h > 0),
    default_settings jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(default_settings) = 'object'),
    CHECK (default_x + default_w <= 1 AND default_y + default_h <= 1)
);


-- How one person has one widget set up. Every person has a row for every widget, so
-- reading a layout never has to fill in gaps.
CREATE TABLE person_widget (
    person_id  bigint NOT NULL REFERENCES person ON DELETE CASCADE,
    widget_key text NOT NULL REFERENCES widget ON UPDATE CASCADE ON DELETE CASCADE,
    enabled    boolean NOT NULL,
    -- Top-left corner (x, y) and size (w, h), as screen fractions.
    x          screen_fraction NOT NULL,
    y          screen_fraction NOT NULL,
    w          screen_fraction NOT NULL CHECK (w > 0),
    h          screen_fraction NOT NULL CHECK (h > 0),
    -- Per-widget options, e.g. {"city": "Poughkeepsie"} for weather.
    settings   jsonb NOT NULL CHECK (jsonb_typeof(settings) = 'object'),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (person_id, widget_key),
    CHECK (x + w <= 1 AND y + h <= 1)
);

CREATE TRIGGER person_widget_touch BEFORE UPDATE ON person_widget
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- A new person gets every widget at its default layout.
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

-- A newly added widget is given to everyone who already exists.
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
