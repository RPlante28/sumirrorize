-- Each person's Brightspace login, so d3l can fetch their data without them signing in
-- every time. Anyone holding these cookies is signed in as that student, so d3l encrypts
-- them (AES-256-GCM, key in d3l's .env) before they get here.
CREATE TABLE brightspace_session (
    person_id    bigint PRIMARY KEY REFERENCES person ON DELETE CASCADE,
    cookies      bytea NOT NULL,
    -- When the person last signed in themselves (background refreshes don't change it).
    signed_in_at timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER brightspace_session_touch BEFORE UPDATE ON brightspace_session
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
